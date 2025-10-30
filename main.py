import logging
import os
import sys
import time
from datetime import datetime, timezone

from dotenv import load_dotenv

from api.client import ApiClient
from data.enums import ShipAction, ShipRole
from data.models.runtime import ShipState
from data.warehouse import Warehouse
from flow.queue import MinHeap
from logic.markets import Markets
from logic.navigation import Navigation
from logic.navigation_algorithms import NavigationAlgorithms
from logic.scanner import Scanner
from policy.dispatcher import Dispatcher

# load environment variables
load_dotenv()

# logging.basicConfig(level=logging.DEBUG, format="%(asctime)s - %(levelname)s - %(message)s")
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

# Validate required environment variables
agent_token = os.getenv("AGENT_TOKEN")
if not agent_token:
    logging.error("Error: AGENT_TOKEN not found in environment.")
    logging.error("Please set AGENT_TOKEN in your .env file or environment.")
    sys.exit(1)

logging.info("Systems initializing")

# create an api instance to hold the key for all api calls
client = ApiClient(agent_token)
dataWarehouse = Warehouse()
scanner = Scanner(client, dataWarehouse)
navigator = Navigation(client, dataWarehouse)
navigatorAlgorithms = NavigationAlgorithms(client, dataWarehouse)
markets = Markets(client, dataWarehouse)

logging.info("All systems operational.")
try:
    # Hydrate market data from SQLite so prices survive restarts
    dataWarehouse.load_market_data_from_storage()
    logging.info(f"Loaded {len(dataWarehouse.market_prices_by_waypoint)} market waypoints from storage")
except Exception:
    pass
credits = scanner.get_credits()
logging.info(f"Credits: {credits}")

event_queue = MinHeap()
dispatcher = Dispatcher(dataWarehouse, scanner, event_queue)
dispatcher.update_fleet()

# Initialize the minHeap with the ships, using the shipReadiness as the priority
for ship in dataWarehouse.ships_by_symbol.values():
    event_queue.push(ship.symbol, dispatcher.shipReadiness(ship.symbol))
    logging.info(
        f"Ship added to event queue:\n"
        f"- Ship: {ship.symbol} - {ship.registration.role}\n"
        f"- Readiness: {dispatcher.shipReadiness(ship.symbol)}\n"
        f"- Cargo: {ship.cargo.units}/{ship.cargo.capacity}\n"
        f"- Fuel: {ship.fuel.current}/{ship.fuel.capacity}"
    )
# log the intial size of the queue
logging.info(f"Initial size of event queue: {event_queue.size()}")


# Helper: parse ISO-8601 UTC timestamp (with trailing Z) to aware datetime
def _parse_iso_utc(ts: str) -> datetime:
    logging.debug(f"_parse_iso_utc: raw ts={ts!r}")
    if not ts:
        dt = datetime.now(timezone.utc)
        logging.debug(f"_parse_iso_utc: empty ts → now={dt.isoformat()}")
        return dt
    if ts.endswith("Z"):
        ts = ts[:-1] + "+00:00"
    dt = datetime.fromisoformat(ts)
    logging.debug(f"_parse_iso_utc: parsed dt={dt.isoformat()}")
    return dt


while True:
    next_priority = event_queue.peek_next_priority()
    logging.debug(f"Next event queue priority (ISO): {next_priority}")
    if next_priority is None:
        logging.info("No ships in event queue")
        break
    # Non-blocking bounded sleep: parse ISO timestamps and sleep a very short interval
    now_dt = datetime.now(timezone.utc)
    # next_priority is an ISO-8601 string from shipReadiness
    try:
        target_dt = _parse_iso_utc(next_priority)
        wait_s = max(0.0, (target_dt - now_dt).total_seconds())
        logging.debug(
            f"Scheduler timing: now={now_dt.isoformat()}, target={target_dt.isoformat()}, wait_s={wait_s:.3f}"
        )
    except Exception:
        logging.debug(f"Failed to parse next_priority {next_priority!r}; proceeding without wait.")
        wait_s = 0.0
    if wait_s > 0:
        sleep_s = max(0.05, min(wait_s, 0.5))
        logging.debug(f"Sleeping for {sleep_s:.3f}s (remaining {wait_s:.3f}s)")
        time.sleep(sleep_s)
        continue
    event = event_queue.extract_min()
    logging.debug(f"Dequeued event: {event} (previous target {next_priority})")
    if event is None:
        logging.info("No ships in event queue")
        break
    ship = dataWarehouse.ships_by_symbol.get(event)
    if ship is None:
        logging.error(f"Ship no longer exists: {event}")
        continue
    # Decide exactly one action to take, then execute it.
    action = dispatcher.decide_next_action(ship.symbol)
    if action != ShipAction.NOOP:
        logging.info(
            f"Ship: {ship.symbol} - Fuel: {ship.fuel.current}/{ship.fuel.capacity} - Cargo: {ship.cargo.units}/{ship.cargo.capacity} - Action: {action}"
        )
    else:
        logging.debug(
            f"Ship: {ship.symbol} - Fuel: {ship.fuel.current}/{ship.fuel.capacity} - Cargo: {ship.cargo.units}/{ship.cargo.capacity} - Action: NOOP"
        )
    if action == ShipAction.REFUEL:
        # Use Markets helper so BUY tx is recorded and credits are updated
        ship = markets.refuel_if_available(ship.symbol)
        # FSM: transient refuel -> back to IDLE and ready now
        rt = dataWarehouse.runtime.get(ship.symbol)
        if rt:
            rt.state = ShipState.IDLE
        logging.info(
            f"Refueled ship: {ship.symbol} - Fuel: {ship.fuel.current}/{ship.fuel.capacity} - Credits: {dataWarehouse.credits}"
        )
    elif action == ShipAction.NAVIGATE_TO_MINE:
        closest_mineable_waypoint = navigatorAlgorithms.find_closest_mineable_waypoint(ship.symbol)
        logging.info(f"Closest mineable waypoint: {closest_mineable_waypoint}")
        if closest_mineable_waypoint:
            ship = navigator.navigate_in_system(ship.symbol, closest_mineable_waypoint)
            # FSM: now navigating towards mine; wakeup at arrival
            rt = dataWarehouse.runtime.get(ship.symbol)
            if rt and ship and ship.nav and ship.nav.route:
                rt.state = ShipState.NAVIGATING
                rt.context["destination"] = "MINE"
            logging.info(f"Navigating to {closest_mineable_waypoint}")
    elif action == ShipAction.EXTRACT_MINERALS:
        navigator.extract_at_current_waypoint(ship.symbol)
        # Refresh ship to get cooldown
        ship = dataWarehouse.ships_by_symbol.get(ship.symbol)
        # FSM: mining -> wakeup at cooldown expiration
        rt = dataWarehouse.runtime.get(ship.symbol)
        if rt and ship and ship.cooldown:
            rt.state = ShipState.MINING
    elif action == ShipAction.PROBE_VISIT_MARKET:
        # Navigate to target marketplace and reveal prices
        rt = dataWarehouse.runtime.get(ship.symbol)
        target = rt.context.get("target_market") if rt else None
        if not target:
            logging.info(f"Probe target not set for {ship.symbol}; skipping.")
        else:
            logging.info(f"Probe navigating to market: {target}")
            # Set transient state to indicate probe travel
            if rt and ship and ship.nav and ship.nav.route is not None:
                rt.state = ShipState.NAVIGATING
                rt.context["destination"] = "PROBE_MARKET"
            ship = navigator.navigate_in_system(ship.symbol, target)
            ship = navigator.wait_until_arrival(ship.symbol)
            # Upon arrival, fetch and upsert market snapshot (triggers INFO price logs)
            try:
                system_symbol = ship.nav.systemSymbol if ship and ship.nav else None
                if system_symbol:
                    market = client.waypoints.get_market(system_symbol, target)
                    if market:
                        dataWarehouse.upsert_market_snapshot(system_symbol, market)
                        goods = market.get("tradeGoods", []) if isinstance(market, dict) else []
                        for good in goods:
                            dataWarehouse.record_good_observation(system_symbol, target, good)
                        logging.info(f"Probe visited {target}; observed {len(goods)} goods")
                        # If this is an EXCAVATOR with cargo, attempt to sell here
                        try:
                            if ship.registration and ship.registration.role == ShipRole.EXCAVATOR:
                                if ship.cargo and ship.cargo.units > 0:
                                    ship = markets.dock_and_sell_all_cargo(ship.symbol, target)
                        except Exception:
                            pass
            except Exception as e:
                logging.error(f"Probe market fetch failed at {target}: {e}")
            # Reset to IDLE for next hop
            if rt:
                rt.state = ShipState.IDLE
                rt.context.pop("target_market", None)
                rt.context.pop("destination", None)
    # Always re-queue after one action (or no-op)
    # add ship back to the event queue
    readiness = dispatcher.shipReadiness(ship.symbol)
    logging.debug(f"Re-queueing {ship.symbol} with readiness={readiness}")
    event_queue.push(ship.symbol, readiness)
    if action != ShipAction.NOOP:
        logging.info(
            f"Ship added back to event queue: {ship.symbol} - {ship.registration.role} - Readiness: {readiness}"
        )

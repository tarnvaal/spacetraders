from dotenv import load_dotenv
import os
import sys
import configparser
import time

from api.client import ApiClient
from data.warehouse import Warehouse
from data.enums import WaypointTraitType, ShipRole
from logic.scanner import Scanner
from logic.mine import Mine
from logic.navigation import Navigation

# load environment variables
load_dotenv()

# Validate required environment variables
agent_token = os.getenv("AGENT_TOKEN")
if not agent_token:
    print("Error: AGENT_TOKEN not found in environment.", file=sys.stderr)
    print("Please set AGENT_TOKEN in your .env file or environment.", file=sys.stderr)
    sys.exit(1)

#create an api instance to hold the key for all api calls
client = ApiClient(agent_token)
dataWarehouse = Warehouse()  
scanner = Scanner(client, dataWarehouse)
navigator = Navigation(client, dataWarehouse)

# load optional config.ini
config = configparser.ConfigParser()
config_path = os.path.join(os.path.dirname(__file__), "config.ini")
if os.path.exists(config_path):
    config.read(config_path)

scan_shipyards = config.getboolean("scanner", "scan_shipyards", fallback=False) if config.has_section("scanner") else False
print_shipyards = config.getboolean("scanner", "print_shipyards", fallback=False) if config.has_section("scanner") else False
print_fleet = config.getboolean("scanner", "print_fleet", fallback=False) if config.has_section("scanner") else False
scan_market_prices = config.getboolean("scanner", "scan_market_prices", fallback=False) if config.has_section("scanner") else False
print_market_observations = config.getboolean("scanner", "print_market_observations", fallback=False) if config.has_section("scanner") else False
market_observation_good = config.get("scanner", "observation_good", fallback="").strip() if config.has_section("scanner") else ""
do_quickstart_mine = config.getboolean("navigation", "quickstart_mine", fallback=False) if config.has_section("navigation") else False
scheduler_enabled = config.getboolean("navigation", "scheduler_enabled", fallback=False) if config.has_section("navigation") else False
scheduler_sleep_s = config.getint("navigation", "scheduler_sleep_seconds", fallback=3) if config.has_section("navigation") else 3

scanner.print_hq_system()
scanner.scan_systems()
if scan_shipyards:
    scanner.scan_waypoints_by_type(WaypointTraitType.SHIPYARD)
if print_shipyards:
    scanner.print_waypoints_by_type(WaypointTraitType.SHIPYARD)
scanner.scan_fleet()
if print_fleet:
    scanner.print_fleet()
dataWarehouse.print_warehouse_size()

# Print all ship roles for debugging
print("\nFleet composition:")
for ship in dataWarehouse.ships_by_symbol.values():
    role = ship.registration.role.value if ship.registration and ship.registration.role else "UNKNOWN"
    print(f"  {ship.symbol}: {role}")

if scan_market_prices:
    scanner.scan_marketplaces_with_probe()
if print_market_observations:
    if market_observation_good:
        scanner.print_known_market_observations(market_observation_good)
    else:
        scanner.print_known_market_observations()

miner = Mine(client, dataWarehouse)
miner.mine()

def _is_ship_busy(sym: str) -> bool:
    ship = dataWarehouse.ships_by_symbol.get(sym)
    if not ship or not ship.nav:
        return False
    # Busy if in transit or under cooldown
    if ship.nav.status and ship.nav.status.value == "IN_TRANSIT":
        return True
    if ship.cooldown and ship.cooldown.remainingSeconds and ship.cooldown.remainingSeconds > 0:
        return True
    return False

def _is_marketplace(wp_symbol: str) -> bool:
    try:
        # Use navigator helper; falls back to fetching details
        return navigator._waypoint_has_trait(wp_symbol, WaypointTraitType.MARKETPLACE)  # type: ignore[attr-defined]
    except Exception:
        return False

def _best_market_for_ship(sym: str) -> str:
    return navigator.find_best_marketplace_for_cargo(sym)

def _can_market_buy_cargo(sym: str, market_wp_symbol: str) -> bool:
    """Check if a marketplace can buy any of the ship's cargo items."""
    try:
        ship = dataWarehouse.ships_by_symbol.get(sym)
        if not ship or not ship.cargo or ship.cargo.units == 0:
            return False
        
        # Get ship's cargo
        cargo_payload = client.fleet.get_cargo(sym)
        inventory = (cargo_payload.get('data') or {}).get('inventory', []) if isinstance(cargo_payload, dict) else []
        if not inventory:
            return False
        cargo_syms = {i.get('symbol') for i in inventory if i.get('symbol')}
        
        # Get market's accepted goods
        system_symbol = ship.nav.systemSymbol
        market = client.waypoints.get_market(system_symbol, market_wp_symbol)
        if not market:
            return False
        
        # Update warehouse with market data
        dataWarehouse.upsert_market_snapshot(system_symbol, market)
        for good in market.get('tradeGoods', []) or []:
            dataWarehouse.record_good_observation(system_symbol, market_wp_symbol, good)
        
        goods = market.get('tradeGoods', []) if isinstance(market, dict) else []
        sellable = {g.get('symbol') for g in goods if g.get('symbol') and g.get('sellPrice', 0) > 0}
        
        # Check if any cargo can be sold
        return bool(sellable & cargo_syms)
    except Exception as e:
        print(f"[Market Check] Error checking market {market_wp_symbol}: {e}")
        return False

def run_scheduler():
    # Build ship lists
    miners = [s.symbol for s in dataWarehouse.ships_by_symbol.values() if s.registration and s.registration.role == ShipRole.EXCAVATOR]
    probe = next((s.symbol for s in dataWarehouse.ships_by_symbol.values() if s.registration and s.registration.role == ShipRole.SATELLITE), None)
    ship_order = miners + ([probe] if probe else [])
    if not ship_order:
        print("[Scheduler] No ships to manage")
        return
    
    print(f"[Scheduler] Managing {len(miners)} miner(s) and {'1 probe' if probe else 'no probe'}")
    if probe:
        print(f"[Scheduler] Probe: {probe}")
    for miner in miners:
        print(f"[Scheduler] Miner: {miner}")

    # Per-ship queues
    queues: dict[str, list[tuple[str, dict]]] = {s: [] for s in ship_order}
    last_stats_time: float = 0.0

    def print_stats():
        try:
            agent = client.agent.get().get('data', {})
            if agent:
                dataWarehouse.load_agent_data(agent)
        except Exception:
            pass
        print(f"[Stats] Credits: {dataWarehouse.credits}")
        for s in dataWarehouse.ships_by_symbol.values():
            if s.cargo and s.cargo.capacity and s.cargo.capacity > 0:
                print(f"[Stats] {s.symbol} cargo {s.cargo.units}/{s.cargo.capacity}")

    def enqueue(sym: str, action: str, **kwargs):
        queues[sym].append((action, kwargs))

    def plan_next(sym: str):
        ship = dataWarehouse.ships_by_symbol.get(sym)
        if not ship:
            return
        # Probe behavior: continuously scan marketplaces
        from data.enums import ShipRole as _ShipRole
        if ship.registration and ship.registration.role == _ShipRole.SATELLITE:
            # Get markets list in current system
            system_symbol = ship.nav.systemSymbol
            markets = client.waypoints.find_waypoints_by_trait(system_symbol, WaypointTraitType.MARKETPLACE)
            
            if markets:
                # Find unvisited markets first
                unvisited = [m for m in markets if m.get('symbol') and m.get('symbol') not in dataWarehouse.market_prices_by_waypoint]
                
                if unvisited:
                    # Prioritize unvisited markets
                    target = next((m.get('symbol') for m in unvisited if m.get('symbol') != ship.nav.waypointSymbol), None)
                    if not target and len(unvisited) == 1:
                        # Only one unvisited market and we're at it
                        target = unvisited[0].get('symbol')
                else:
                    # All visited, rescan in round-robin fashion
                    target = next((m.get('symbol') for m in markets if m.get('symbol') and m.get('symbol') != ship.nav.waypointSymbol), None)
                
                if target:
                    print(f"[Probe][{sym}] Next target: {target}")
                    enqueue(sym, 'navigate', waypoint=target)
                    enqueue(sym, 'dock')
                    enqueue(sym, 'refuel')
                    enqueue(sym, 'market_scan')
                    enqueue(sym, 'orbit')
                elif ship.nav.waypointSymbol in [m.get('symbol') for m in markets]:
                    # Already at a market, just scan it
                    enqueue(sym, 'dock')
                    enqueue(sym, 'refuel')
                    enqueue(sym, 'market_scan')
                    enqueue(sym, 'orbit')
            return

        # Miner behavior per policy
        at_market = _is_marketplace(ship.nav.waypointSymbol)
        cargo_full = ship.cargo.units >= ship.cargo.capacity > 0
        has_cargo = ship.cargo.units > 0
        # Prefer selling whenever we have any cargo
        if cargo_full or has_cargo:
            if at_market:
                # Check if THIS market can buy our cargo
                can_sell_here = _can_market_buy_cargo(sym, ship.nav.waypointSymbol)
                if can_sell_here:
                    print(f"[Sched][{sym}] Market accepts cargo, selling here")
                    enqueue(sym, 'dock')
                    enqueue(sym, 'refuel')
                    enqueue(sym, 'sell_here')
                    enqueue(sym, 'orbit')
                    return
                else:
                    print(f"[Sched][{sym}] Current market doesn't buy cargo, finding better market")
                    # Fall through to find better market
            
            # Not at market or current market doesn't buy our cargo
            try:
                target = _best_market_for_ship(sym)
            except Exception as e:
                print(f"[Sched][{sym}] Error finding market: {e}")
                target = None
            if target and target != ship.nav.waypointSymbol:
                enqueue(sym, 'navigate', waypoint=target)
                enqueue(sym, 'dock')
                enqueue(sym, 'refuel')
                enqueue(sym, 'sell_here')
                enqueue(sym, 'orbit')
                return
            # No known buyer: wait for probe to discover markets
            print(f"[Sched][{sym}] No buyer found, waiting for market discovery")
            return
        # No cargo: go mine
        try:
            target_mine = navigator.find_closest_mineable_waypoint(sym)
        except Exception:
            target_mine = None
        if target_mine and target_mine != ship.nav.waypointSymbol:
            enqueue(sym, 'navigate', waypoint=target_mine)
        # If at market and can refuel, do so before mining
        if at_market:
            enqueue(sym, 'dock')
            enqueue(sym, 'refuel')
            enqueue(sym, 'orbit')
        enqueue(sym, 'mine_once')

    def step(sym: str):
        ship = navigator._refresh_ship(sym)  # refresh state
        if _is_ship_busy(sym):
            return False
        if not queues[sym]:
            plan_next(sym)
            if not queues[sym]:
                return False
        action, kwargs = queues[sym].pop(0)
        if action == 'navigate':
            wp = kwargs.get('waypoint')
            print(f"[Sched][{sym}] Navigate to {wp}")
            navigator.navigate_in_system(sym, wp)
            return True
        if action == 'dock':
            print(f"[Sched][{sym}] Docking")
            navigator._ensure_docked(sym)
            return True
        if action == 'refuel':
            ship = navigator._refresh_ship(sym)
            if ship.fuel.current < ship.fuel.capacity:
                print(f"[Sched][{sym}] Refueling if available")
                try:
                    navigator.refuel_if_available(sym)
                except Exception:
                    print(f"[Sched][{sym}] Refuel not available here")
            return True
        if action == 'orbit':
            print(f"[Sched][{sym}] Orbiting")
            navigator._ensure_orbit(sym)
            return True
        if action == 'market_scan':
            ship = navigator._refresh_ship(sym)
            system_symbol = ship.nav.systemSymbol
            wp_symbol = ship.nav.waypointSymbol
            print(f"[Probe][{sym}] Scanning market at {wp_symbol}")
            market = client.waypoints.get_market(system_symbol, wp_symbol)
            if market:
                dataWarehouse.upsert_market_snapshot(system_symbol, market)
                goods = market.get('tradeGoods', []) or []
                for good in goods:
                    dataWarehouse.record_good_observation(system_symbol, wp_symbol, good)
                # Log what the market buys
                buy_symbols = {g.get('symbol') for g in goods if g.get('symbol')}
                print(f"[Probe][{sym}] Market {wp_symbol} buys: {', '.join(sorted(buy_symbols)) if buy_symbols else 'nothing'}")
            else:
                print(f"[Probe][{sym}] No market data available at {wp_symbol}")
            return True
        if action == 'sell_here':
            ship = navigator._refresh_ship(sym)
            print(f"[Sched][{sym}] Selling cargo at {ship.nav.waypointSymbol}")
            navigator.dock_and_sell_all_cargo(sym, ship.nav.waypointSymbol)
            return True
        if action == 'mine_once':
            # Ensure orbit, extract once, set next_ready to cooldown
            print(f"[Sched][{sym}] Mining once")
            navigator._ensure_orbit(sym)
            resp = navigator.extract_at_current_waypoint(sym)
            ship = navigator._refresh_ship(sym)
            return True
        # Unknown action
        return False

    # Round-robin cooperative loop
    try:
        while True if scheduler_enabled else False:
            for sym in ship_order:
                step(sym)
            time.sleep(max(0.1, scheduler_sleep_s))
            # Periodic stats every ~60s
            now = time.time()
            if now - last_stats_time >= 60:
                print_stats()
                last_stats_time = now
    except KeyboardInterrupt:
        print("[Scheduler] Stopped")

if not scheduler_enabled and do_quickstart_mine:
    # Existing sequential flow
    configured_symbol = config.get("navigation", "ship_symbol", fallback="").strip() if config.has_section("navigation") else ""
    excavators = [s.symbol for s in dataWarehouse.ships_by_symbol.values() if s.registration and s.registration.role == ShipRole.EXCAVATOR]
    if not excavators:
        print("[Quickstart] No excavator ships found")
    else:
        ordered_symbols = list(dict.fromkeys(([configured_symbol] if configured_symbol else []) + excavators))
        try:
            while True:
                for sym in ordered_symbols:
                    print(f"[Quickstart] Processing {sym}...")
                    ship = navigator.quickstart_mine_until_full_and_sell(sym)
                    print(f"[Quickstart] Loop Done {sym}: {(ship.nav.status.value if ship.nav.status else '?')} @ {ship.nav.systemSymbol}/{ship.nav.waypointSymbol} | Cargo {ship.cargo.units}/{ship.cargo.capacity}")
                # credits logging
                try:
                    # ensure logs dir
                    logs_dir = os.path.join(os.path.dirname(__file__), "logs")
                    if not os.path.isdir(logs_dir):
                        os.makedirs(logs_dir, exist_ok=True)
                    # refresh agent credits
                    agent = client.agent.get().get('data', {})
                    if agent:
                        dataWarehouse.load_agent_data(agent)
                    # append UTC timestamp and credits
                    ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
                    with open(os.path.join(logs_dir, "credits.log"), "a", encoding="utf-8") as f:
                        f.write(f"{ts}\t{dataWarehouse.credits}\n")
                except Exception as e:
                    print(f"[Log] Failed to write credits log: {e}")
        except KeyboardInterrupt:
            print("[Quickstart] Stopped")

if scheduler_enabled:
    run_scheduler()

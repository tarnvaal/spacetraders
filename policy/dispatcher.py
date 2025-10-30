import logging
import math

from data.enums import ShipAction, ShipRole
from data.models.runtime import ShipRuntime, ShipState
from data.warehouse import Warehouse
from flow.queue import MinHeap
from logic.markets import Markets
from logic.scanner import Scanner
from logic.utility import get_utc_timestamp


class Dispatcher:
    def __init__(self, warehouse: Warehouse, scanner: Scanner, event_queue: MinHeap):
        self.warehouse = warehouse
        self.scanner = scanner
        self.event_queue = event_queue
        # Helper for market-related selections (distance, unvisited markets)
        self.markets = Markets(scanner.client, warehouse)

    def update_fleet(self):
        self.scanner.scan_fleet(all_pages=True)
        logging.info(f"Fleet updated. {len(self.warehouse.ships_by_symbol)} ships found.")
        # Initialize per-ship runtime if missing
        for symbol in self.warehouse.ships_by_symbol.keys():
            if symbol not in self.warehouse.runtime:
                self.warehouse.runtime[symbol] = ShipRuntime()

    def shipReadiness(self, symbol: str):
        # Prefer FSM-planned wakeup time
        rt = self.warehouse.runtime.get(symbol)
        if rt and rt.next_wakeup_ts:
            current = get_utc_timestamp()
            chosen = max(rt.next_wakeup_ts, current)
            logging.debug(
                f"shipReadiness[{symbol}]: rt.next_wakeup_ts={rt.next_wakeup_ts} current={current} → chosen={chosen}"
            )
            return chosen
        # Fallback to ship timers
        ship = self.warehouse.ships_by_symbol.get(symbol)
        if ship is None:
            ts = get_utc_timestamp()
            logging.debug(f"shipReadiness[{symbol}]: ship missing, fallback now={ts}")
            return ts
        arrival = ship.nav.route.arrival if ship.nav and ship.nav.route else ""
        cooldown = ship.cooldown.expiration if ship.cooldown else ""
        current = get_utc_timestamp()
        chosen = max(arrival or current, cooldown or current, current)
        logging.debug(
            f"shipReadiness[{symbol}]: arrival={arrival} cooldown={cooldown} current={current} → chosen={chosen}"
        )
        return chosen

    def decide_next_action(self, symbol: str) -> ShipAction:
        ship = self.warehouse.ships_by_symbol.get(symbol)
        rt = self.warehouse.runtime.get(symbol)
        if ship is None or rt is None:
            return ShipAction.NOOP

        # Helper: does current waypoint sell fuel (based on known snapshot only)
        def _current_wp_sells_fuel() -> bool:
            wp = ship.nav.waypointSymbol if ship and ship.nav else None
            if not wp:
                return False
            snapshot = self.warehouse.market_prices_by_waypoint.get(wp)
            if not isinstance(snapshot, dict):
                return False
            goods = snapshot.get("tradeGoods")
            if not isinstance(goods, list):
                return False
            for g in goods:
                if not isinstance(g, dict):
                    continue
                if g.get("symbol") == "FUEL":
                    price = g.get("purchasePrice")
                    if isinstance(price, int | float) and price > 0:
                        return True
            return False

        state = rt.state if isinstance(rt.state, ShipState) else ShipState.IDLE
        nav_status = getattr(getattr(ship, "nav", None), "status", None)
        arrival = ship.nav.route.arrival if ship.nav and ship.nav.route else ""
        cooldown = ship.cooldown.expiration if ship.cooldown else ""
        logging.debug(
            f"decide_next_action[{symbol}]: state={state} fuel={ship.fuel.current}/{ship.fuel.capacity} "
            f"cargo={ship.cargo.units}/{ship.cargo.capacity} nav_status={nav_status} arrival={arrival} cooldown={cooldown} "
            f"ctx={rt.context}"
        )

        if state == ShipState.IDLE:
            # Refuel only if current location is known to sell fuel
            if ship.fuel.current < ship.fuel.capacity and _current_wp_sells_fuel():
                logging.debug(f"decide_next_action[{symbol}]: choosing REFUEL")
                return ShipAction.REFUEL
            # Probe behavior: visit marketplaces to reveal prices
            if ship.registration and ship.registration.role == ShipRole.SATELLITE:
                try:
                    # Avoid duplicate targets already assigned to others
                    exclude = {
                        r.context.get("target_market")
                        for r in self.warehouse.runtime.values()
                        if isinstance(r.context.get("target_market"), str)
                    }
                    target = self.markets.find_nearest_unvisited_marketplace(symbol, exclude=exclude)
                    if not target:
                        target = self.markets.find_nearest_marketplace(symbol, exclude=exclude)
                    if target and rt is not None:
                        rt.context["target_market"] = target
                        logging.debug(f"decide_next_action[{symbol}]: choosing PROBE_VISIT_MARKET -> {target}")
                        return ShipAction.PROBE_VISIT_MARKET
                except Exception:
                    pass
            # Mine behavior for excavators: purge unsellable items; mine until full; then sell at known buyers.
            if ship.registration and ship.registration.role == ShipRole.EXCAVATOR:
                # Helper: jettison goods that have no known buyers in cached market snapshots
                def _jettison_unsellable() -> bool:
                    try:
                        cargo_payload = self.scanner.client.fleet.get_cargo(symbol)
                        inventory = (
                            (cargo_payload.get("data") or {}).get("inventory", [])
                            if isinstance(cargo_payload, dict)
                            else []
                        )
                        if not inventory:
                            return False
                        known_buyers: set[str] = set()
                        for snapshot in self.warehouse.market_prices_by_waypoint.values():
                            goods = snapshot.get("tradeGoods", []) if isinstance(snapshot, dict) else []
                            for g in goods:
                                if not isinstance(g, dict):
                                    continue
                                if g.get("sellPrice", 0) and g.get("symbol"):
                                    known_buyers.add(g.get("symbol"))
                        did = False
                        for item in inventory:
                            gsym = item.get("symbol")
                            units = item.get("units", 0)
                            if not gsym or not units:
                                continue
                            if gsym not in known_buyers:
                                try:
                                    self.scanner.client.fleet.jettison(symbol, gsym, units)
                                    did = True
                                except Exception:
                                    pass
                        return did
                    except Exception:
                        return False

                # If not full, purge unsellable items and keep mining
                if ship.cargo and ship.cargo.units < ship.cargo.capacity:
                    try:
                        _jettison_unsellable()
                    except Exception:
                        pass
                    logging.debug(f"decide_next_action[{symbol}]: choosing NAVIGATE_TO_MINE")
                    return ShipAction.NAVIGATE_TO_MINE

                # If full, pick nearest known buyer (from cached snapshots) and go sell; otherwise jettison unsellables and resume mining
                if ship.cargo and ship.cargo.units >= ship.cargo.capacity:
                    try:
                        cargo_payload = self.scanner.client.fleet.get_cargo(symbol)
                        inventory = (
                            (cargo_payload.get("data") or {}).get("inventory", [])
                            if isinstance(cargo_payload, dict)
                            else []
                        )
                        cargo_syms = {i.get("symbol") for i in inventory if isinstance(i, dict) and i.get("symbol")}

                        def _dist(a_sym: str, b_sym: str) -> float:
                            a = self.warehouse.waypoints_by_symbol.get(a_sym)
                            b = self.warehouse.waypoints_by_symbol.get(b_sym)
                            if not a or not b:
                                return float("inf")
                            dx = (a.x or 0) - (b.x or 0)
                            dy = (a.y or 0) - (b.y or 0)
                            return math.hypot(dx, dy)

                        current_wp = ship.nav.waypointSymbol if ship and ship.nav else None
                        best_sym = None
                        best_dist = None
                        if current_wp and cargo_syms:
                            for wp_sym, snapshot in self.warehouse.market_prices_by_waypoint.items():
                                goods = snapshot.get("tradeGoods", []) if isinstance(snapshot, dict) else []
                                sellable = {
                                    g.get("symbol") for g in goods if isinstance(g, dict) and g.get("sellPrice", 0) > 0
                                }
                                if not (sellable & cargo_syms):
                                    continue
                                d = _dist(current_wp, wp_sym)
                                if best_dist is None or d < best_dist:
                                    best_sym, best_dist = wp_sym, d
                        if best_sym:
                            rt.context["target_market"] = best_sym
                            logging.debug(
                                f"decide_next_action[{symbol}]: cargo full, targeting PROBE_VISIT_MARKET -> {best_sym}"
                            )
                            return ShipAction.PROBE_VISIT_MARKET

                        # No known buyers -> jettison unsellables and resume mining
                        try:
                            if _jettison_unsellable():
                                logging.debug(f"decide_next_action[{symbol}]: jettisoned unsellables; resume mining")
                                return ShipAction.NAVIGATE_TO_MINE
                        except Exception:
                            pass
                    except Exception:
                        pass
            return ShipAction.NOOP

        if state == ShipState.NAVIGATING:
            if rt.context.get("destination") == "MINE":
                logging.debug(f"decide_next_action[{symbol}]: NAVIGATING→EXTRACT_MINERALS")
                return ShipAction.EXTRACT_MINERALS
            return ShipAction.NOOP

        if state == ShipState.MINING:
            if ship.cargo and ship.cargo.units < ship.cargo.capacity:
                logging.debug(f"decide_next_action[{symbol}]: MINING continue EXTRACT_MINERALS")
                return ShipAction.EXTRACT_MINERALS
            return ShipAction.NOOP

        return ShipAction.NOOP

import logging

from data.enums import ShipAction, ShipNavStatus, ShipRole, WaypointTraitType
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
            # Refuel only if current location is known to sell fuel and not in transit
            if (
                ship.fuel.current < ship.fuel.capacity
                and _current_wp_sells_fuel()
                and nav_status != ShipNavStatus.IN_TRANSIT
            ):
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
                        # When no unvisited markets remain, scout the oldest visited marketplace in-system
                        target = self.markets.find_oldest_marketplace(
                            symbol, exclude=exclude
                        ) or self.markets.find_nearest_marketplace(symbol, exclude=exclude)
                    if target and rt is not None:
                        rt.context["target_market"] = target
                        logging.debug(f"decide_next_action[{symbol}]: choosing PROBE_VISIT_MARKET -> {target}")
                        return ShipAction.PROBE_VISIT_MARKET
                except Exception:
                    pass
            # Mine behavior for excavators: if in selling mode, continue selling until empty; otherwise mine until full of worthy goods then sell.
            if ship.registration and ship.registration.role == ShipRole.EXCAVATOR:
                # Continue selling loop if flagged
                if rt.context.get("selling"):
                    if ship.cargo and ship.cargo.units > 0:
                        # If a target is already assigned, keep heading there
                        target = rt.context.get("target_market")
                        if isinstance(target, str) and target:
                            logging.debug(f"decide_next_action[{symbol}]: selling mode active, heading to {target}")
                            return ShipAction.PROBE_VISIT_MARKET
                        # Otherwise, choose next known buyer based on cached snapshots
                        try:
                            cargo_payload = self.scanner.client.fleet.get_cargo(symbol)
                            inventory = (
                                (cargo_payload.get("data") or {}).get("inventory", [])
                                if isinstance(cargo_payload, dict)
                                else []
                            )
                            cargo_syms = {i.get("symbol") for i in inventory if isinstance(i, dict) and i.get("symbol")}
                            # Find nearest cached buyer
                            current_wp = ship.nav.waypointSymbol if ship and ship.nav else None
                            best_sym = None
                            best_dist = None
                            if current_wp and cargo_syms:
                                for wp_sym, snapshot in self.warehouse.market_prices_by_waypoint.items():
                                    goods = snapshot.get("tradeGoods", []) if isinstance(snapshot, dict) else []
                                    sellable = {
                                        g.get("symbol")
                                        for g in goods
                                        if isinstance(g, dict) and (g.get("sellPrice", 0) or 0) > 10
                                    }
                                    if not (sellable & cargo_syms):
                                        continue
                                    d = self.markets._waypoint_distance(current_wp, wp_sym)
                                    if best_dist is None or d < best_dist:
                                        best_sym, best_dist = wp_sym, d
                            if best_sym:
                                rt.context["target_market"] = best_sym
                                logging.debug(f"decide_next_action[{symbol}]: selling mode, targeting {best_sym}")
                                return ShipAction.PROBE_VISIT_MARKET
                        except Exception:
                            pass
                        # No known buyers for remaining cargo; mining loop will jettison leftovers at sell site
                        logging.debug(
                            f"decide_next_action[{symbol}]: selling mode but no known buyers; resume mining after cleanup"
                        )
                        return ShipAction.NAVIGATE_TO_MINE
                    # Empty -> exit selling mode
                    rt.context.pop("selling", None)
                    rt.context.pop("target_market", None)
                    logging.debug(f"decide_next_action[{symbol}]: selling complete; resume mining")
                    return ShipAction.NAVIGATE_TO_MINE

                # Helper: jettison goods that have no known buyers or are low-value (<=10) based on best known price
                def _jettison_unworthy(min_price: int = 10) -> bool:
                    try:
                        cargo_payload = self.scanner.client.fleet.get_cargo(symbol)
                        inventory = (
                            (cargo_payload.get("data") or {}).get("inventory", [])
                            if isinstance(cargo_payload, dict)
                            else []
                        )
                        if not inventory:
                            return False

                        # Determine if a good is sellable at acceptable price via observations or cached snapshots
                        def _is_worthy(sym: str) -> bool:
                            best = self.warehouse.get_best_sell_observation(sym)
                            if best and isinstance(best.get("sellPrice"), int | float):
                                return best.get("sellPrice", 0) > min_price
                            # Fallback: any cached snapshot in any market with price > min_price
                            for snapshot in self.warehouse.market_prices_by_waypoint.values():
                                goods = snapshot.get("tradeGoods", []) if isinstance(snapshot, dict) else []
                                for g in goods:
                                    if not isinstance(g, dict):
                                        continue
                                    if g.get("symbol") == sym and (g.get("sellPrice", 0) or 0) > min_price:
                                        return True
                            return False

                        did = False
                        for item in inventory:
                            gsym = item.get("symbol")
                            units = item.get("units", 0)
                            if not gsym or not units:
                                continue
                            if not _is_worthy(gsym):
                                try:
                                    self.scanner.client.fleet.jettison(symbol, gsym, units)
                                    did = True
                                except Exception:
                                    pass
                        return did
                    except Exception:
                        return False

                # If not full, purge unsellable/low-value items and keep mining
                if ship.cargo and ship.cargo.units < ship.cargo.capacity:
                    try:
                        _jettison_unworthy(10)
                    except Exception:
                        pass
                    logging.debug(f"decide_next_action[{symbol}]: choosing NAVIGATE_TO_MINE")
                    return ShipAction.NAVIGATE_TO_MINE

                # If full, and cargo consists of worthy goods, switch to selling; otherwise jettison low-value and resume mining
                if ship.cargo and ship.cargo.units >= ship.cargo.capacity:
                    try:
                        best_market = self.markets.find_best_marketplace_for_cargo(symbol, min_sell_price=10)
                        # Heuristic: if we can find a market buying at least one current cargo good at >=10, switch to selling
                        if isinstance(best_market, str) and best_market:
                            rt.context["target_market"] = best_market
                            rt.context["selling"] = True
                            logging.debug(
                                f"decide_next_action[{symbol}]: cargo full & worthy; selling at {best_market}"
                            )
                            return ShipAction.PROBE_VISIT_MARKET

                        # No worthy buyers -> jettison unworthy and resume mining
                        try:
                            if _jettison_unworthy(10):
                                logging.debug(f"decide_next_action[{symbol}]: jettisoned unsellables; resume mining")
                                return ShipAction.NAVIGATE_TO_MINE
                        except Exception:
                            pass
                    except Exception:
                        pass
            return ShipAction.NOOP

        if state == ShipState.NAVIGATING:
            if rt.context.get("destination") == "MINE":
                # Only extract after arrival at intended mineable waypoint
                if nav_status != ShipNavStatus.IN_TRANSIT:
                    current_wp = ship.nav.waypointSymbol if ship and ship.nav else None
                    target_wp = rt.context.get("mine_target")
                    mineable_traits = [
                        WaypointTraitType.MINERAL_DEPOSITS,
                        WaypointTraitType.COMMON_METAL_DEPOSITS,
                        WaypointTraitType.PRECIOUS_METAL_DEPOSITS,
                        WaypointTraitType.RARE_METAL_DEPOSITS,
                        WaypointTraitType.METHANE_POOLS,
                        WaypointTraitType.ICE_CRYSTALS,
                        WaypointTraitType.EXPLOSIVE_GASES,
                    ]
                    try:
                        if current_wp:
                            has_mine = any(self.markets._waypoint_has_trait(current_wp, t) for t in mineable_traits)
                            if has_mine and (not isinstance(target_wp, str) or current_wp == target_wp):
                                logging.debug(f"decide_next_action[{symbol}]: NAVIGATING→EXTRACT_MINERALS")
                                return ShipAction.EXTRACT_MINERALS
                    except Exception:
                        pass
            return ShipAction.NOOP

        if state == ShipState.MINING:
            if ship.cargo and ship.cargo.units < ship.cargo.capacity:
                logging.debug(f"decide_next_action[{symbol}]: MINING continue EXTRACT_MINERALS")
                return ShipAction.EXTRACT_MINERALS
            return ShipAction.NOOP

        return ShipAction.NOOP

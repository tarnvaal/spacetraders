import logging
import math

from api.client import ApiClient
from data.enums import ShipAction, ShipNavFlightMode, ShipNavStatus, ShipRole
from data.models.runtime import ShipState
from data.warehouse import Warehouse
from logic.markets import Markets
from logic.navigation import Navigation
from logic.navigation_algorithms import NavigationAlgorithms


class ActionExecutor:
    def __init__(
        self,
        client: ApiClient,
        data_warehouse: Warehouse,
        navigator: Navigation,
        navigator_algorithms: NavigationAlgorithms,
        markets: Markets,
    ) -> None:
        self.client = client
        self.data_warehouse = data_warehouse
        self.navigator = navigator
        self.navigator_algorithms = navigator_algorithms
        self.markets = markets

    def execute(self, ship_symbol: str, action: ShipAction) -> None:
        if action == ShipAction.REFUEL:
            self._refuel(ship_symbol)
        elif action == ShipAction.NAVIGATE_TO_MINE:
            self._navigate_to_mine(ship_symbol)
        elif action == ShipAction.EXTRACT_MINERALS:
            self._extract_minerals(ship_symbol)
        elif action == ShipAction.PROBE_VISIT_MARKET:
            self._probe_visit_market(ship_symbol)
        else:
            # NOOP or unknown action — nothing to do
            pass

    # Internal action handlers
    def _refuel(self, ship_symbol: str) -> None:
        ship = self.markets.refuel_if_available(ship_symbol)
        rt = self.data_warehouse.runtime.get(ship_symbol)
        if rt:
            rt.state = ShipState.IDLE
        logging.info(
            f"Refueled ship: {ship.symbol} - Fuel: {ship.fuel.current}/{ship.fuel.capacity} - Credits: {self.data_warehouse.credits}"
        )

    def _navigate_to_mine(self, ship_symbol: str) -> None:
        candidates = self.navigator_algorithms.list_mineable_waypoints_sorted(ship_symbol)
        if not candidates:
            try:
                one = self.navigator_algorithms.find_closest_mineable_waypoint(ship_symbol)
                candidates = [one] if one else []
            except Exception:
                candidates = []
        logging.info(f"Mineable candidates (closest first): {candidates[:5]}{'...' if len(candidates)>5 else ''}")
        rt = self.data_warehouse.runtime.get(ship_symbol)

        # Helper: compute distance from current waypoint to target using warehouse data
        def _distance_to(target_wp: str) -> float:
            try:
                ship_cur = self.data_warehouse.ships_by_symbol.get(ship_symbol) or self.navigator._refresh_ship(
                    ship_symbol
                )
                current_wp = ship_cur.nav.waypointSymbol if ship_cur and ship_cur.nav else None
                if not current_wp:
                    return float("inf")
                return self.navigator._waypoint_distance(current_wp, target_wp)
            except Exception:
                return float("inf")

        def attempt(target: str, mode: ShipNavFlightMode) -> bool:
            # Ensure orbit and set flight mode
            try:
                self.navigator._ensure_orbit(ship_symbol)
            except Exception:
                pass
            try:
                self.navigator._maybe_set_flight_mode(ship_symbol, mode)
            except Exception:
                pass
            # Call raw navigate to inspect errors
            resp = self.client.fleet.navigate_ship(ship_symbol, target)
            if isinstance(resp, dict) and resp.get("error"):
                err = resp.get("error") or {}
                code = err.get("code")
                if code == 4203:
                    data = err.get("data") or {}
                    fuel_req = data.get("fuelRequired")
                    fuel_avail = data.get("fuelAvailable")
                    logging.info(
                        f"Insufficient fuel for {mode.name} to {target}: required={fuel_req} available={fuel_avail}"
                    )
                    return False
                # Other errors
                logging.info(f"Navigate error to {target}: {err}")
                return False
            # Success: apply minimal update via cached ship refresh
            try:
                ship2 = self.data_warehouse.ships_by_symbol.get(ship_symbol) or self.navigator._refresh_ship(
                    ship_symbol
                )
                in_transit2 = ship2.nav.status == ShipNavStatus.IN_TRANSIT if ship2 and ship2.nav else False
                dest2 = (
                    ship2.nav.route.destination.symbol
                    if ship2 and ship2.nav and ship2.nav.route and ship2.nav.route.destination
                    else None
                )
                if rt and in_transit2 and dest2 == target:
                    rt.state = ShipState.NAVIGATING
                    rt.context["destination"] = "MINE"
                    rt.context["mine_target"] = target
                    logging.info(f"Navigating to {target} via {mode.name}")
                    return True
            except Exception:
                pass
            return False

        # Prefer CRUISE only if we can afford it per datastore distance
        try:
            ship = self.data_warehouse.ships_by_symbol.get(ship_symbol) or self.navigator._refresh_ship(ship_symbol)
            fuel_avail = int(getattr(getattr(ship, "fuel", None), "current", 0) or 0)
        except Exception:
            fuel_avail = 0

        # Choose the first candidate that is CRUISE-reachable by simple distance heuristic
        cruise_target: str | None = None
        for tgt in candidates:
            d = _distance_to(tgt)
            if isinstance(d, int | float) and d != float("inf") and math.ceil(d) <= fuel_avail:
                cruise_target = tgt
                break

        if cruise_target:
            if attempt(cruise_target, ShipNavFlightMode.CRUISE):
                return

        # No CRUISE target reachable: drift to best (closest)
        if candidates:
            if attempt(candidates[0], ShipNavFlightMode.DRIFT):
                return

        # Redirect to nearest refuel-capable waypoint (MARKETPLACE)
        try:
            refuel_wp = self.navigator_algorithms.find_closest_refuel_waypoint(ship_symbol)
        except Exception:
            refuel_wp = None

        if isinstance(refuel_wp, str) and refuel_wp:
            d_ref = _distance_to(refuel_wp)
            mode_ref = (
                ShipNavFlightMode.CRUISE
                if isinstance(d_ref, int | float) and d_ref != float("inf") and math.ceil(d_ref) <= fuel_avail
                else ShipNavFlightMode.DRIFT
            )
            # Inline navigate for refuel without setting MINE context
            try:
                self.navigator._ensure_orbit(ship_symbol)
            except Exception:
                pass
            try:
                self.navigator._maybe_set_flight_mode(ship_symbol, mode_ref)
            except Exception:
                pass
            resp2 = self.client.fleet.navigate_ship(ship_symbol, refuel_wp)
            if isinstance(resp2, dict) and resp2.get("error"):
                err2 = resp2.get("error") or {}
                code2 = err2.get("code")
                if code2 == 4203:
                    data2 = err2.get("data") or {}
                    logging.info(
                        f"Insufficient fuel for {mode_ref.name} to {refuel_wp}: required={data2.get('fuelRequired')} available={data2.get('fuelAvailable')}"
                    )
                else:
                    logging.info(f"Navigate error to {refuel_wp}: {err2}")
            else:
                try:
                    ship3 = self.data_warehouse.ships_by_symbol.get(ship_symbol) or self.navigator._refresh_ship(
                        ship_symbol
                    )
                    in_transit3 = ship3.nav.status == ShipNavStatus.IN_TRANSIT if ship3 and ship3.nav else False
                    dest3 = (
                        ship3.nav.route.destination.symbol
                        if ship3 and ship3.nav and ship3.nav.route and ship3.nav.route.destination
                        else None
                    )
                    if rt and in_transit3 and dest3 == refuel_wp:
                        rt.state = ShipState.NAVIGATING
                        rt.context["destination"] = "REFUEL"
                        logging.info(f"Navigating to refuel at {refuel_wp} via {mode_ref.name}")
                        return
                except Exception:
                    pass

        # Backoff if all attempts failed
        if rt:
            from datetime import datetime, timedelta, timezone

            when = datetime.now(timezone.utc) + timedelta(seconds=30)
            rt.next_wakeup_ts = when.isoformat(timespec="milliseconds").replace("+00:00", "Z")
        logging.debug("navigate_to_mine: no reachable targets; backed off")

    def _extract_minerals(self, ship_symbol: str) -> None:
        self.navigator.extract_at_current_waypoint(ship_symbol)
        ship = self.data_warehouse.ships_by_symbol.get(ship_symbol)
        rt = self.data_warehouse.runtime.get(ship_symbol)
        if rt and ship and ship.cooldown:
            rt.state = ShipState.MINING
            # Ensure scheduler sleeps until cooldown expiration even if ship model isn't fully updated
            try:
                exp = getattr(ship.cooldown, "expiration", "")
                if isinstance(exp, str) and exp:
                    rt.next_wakeup_ts = exp
                elif getattr(ship.cooldown, "remainingSeconds", 0):
                    from datetime import datetime, timedelta, timezone

                    rs = int(getattr(ship.cooldown, "remainingSeconds", 0))
                    when = datetime.now(timezone.utc) + timedelta(seconds=max(1, rs))
                    rt.next_wakeup_ts = when.isoformat(timespec="milliseconds").replace("+00:00", "Z")
                else:
                    from datetime import datetime, timedelta, timezone

                    when = datetime.now(timezone.utc) + timedelta(seconds=5)
                    rt.next_wakeup_ts = when.isoformat(timespec="milliseconds").replace("+00:00", "Z")
            except Exception:
                pass

    def _probe_visit_market(self, ship_symbol: str) -> None:
        ship = self.data_warehouse.ships_by_symbol.get(ship_symbol)
        rt = self.data_warehouse.runtime.get(ship_symbol)
        target: str | None = rt.context.get("target_market") if rt else None
        if not target:
            logging.info(f"Probe target not set for {ship_symbol}; skipping.")
            return
        logging.info(f"Probe navigating to market: {target}")
        # If already at target and not in transit, perform market visit and optional selling
        try:
            nav_status = ship.nav.status if ship and ship.nav else None
            at_target = bool(ship and ship.nav and ship.nav.waypointSymbol == target)
            if nav_status != ShipNavStatus.IN_TRANSIT and at_target:
                system_symbol = ship.nav.systemSymbol if ship and ship.nav else None
                if system_symbol:
                    market = self.client.waypoints.get_market(system_symbol, target)
                    if market:
                        self.data_warehouse.upsert_market_snapshot(system_symbol, market)
                        goods = market.get("tradeGoods", []) if isinstance(market, dict) else []
                        for good in goods:
                            self.data_warehouse.record_good_observation(system_symbol, target, good)
                        logging.info(f"Probe visited {target}; observed {len(goods)} goods")
                        # Miners sell only in explicit selling mode; probes never sell
                        try:
                            role = ship.registration.role if ship and ship.registration else None
                            is_miner_selling = bool(role == ShipRole.EXCAVATOR and rt and rt.context.get("selling"))
                            if is_miner_selling and ship.cargo and ship.cargo.units > 0:
                                ship = self.markets.dock_and_sell_all_cargo(ship_symbol, target)
                                try:
                                    cargo_payload = self.client.fleet.get_cargo(ship_symbol)
                                    inventory = (
                                        (cargo_payload.get("data") or {}).get("inventory", [])
                                        if isinstance(cargo_payload, dict)
                                        else []
                                    )
                                    total_units = sum(int(i.get("units", 0)) for i in inventory if isinstance(i, dict))
                                    if total_units > 0 and rt:
                                        cargo_syms = {
                                            i.get("symbol")
                                            for i in inventory
                                            if isinstance(i, dict) and i.get("symbol")
                                        }
                                        current_wp = ship.nav.waypointSymbol if ship and ship.nav else None
                                        best_sym = None
                                        best_dist = None
                                        if current_wp and cargo_syms:
                                            for (
                                                wp_sym,
                                                snapshot,
                                            ) in self.data_warehouse.market_prices_by_waypoint.items():
                                                goods2 = (
                                                    snapshot.get("tradeGoods", []) if isinstance(snapshot, dict) else []
                                                )
                                                sellable = {
                                                    g.get("symbol")
                                                    for g in goods2
                                                    if isinstance(g, dict) and g.get("sellPrice", 0) > 0
                                                }
                                                if not (sellable & cargo_syms):
                                                    continue
                                                d = self.navigator._waypoint_distance(current_wp, wp_sym)
                                                if best_dist is None or d < best_dist:
                                                    best_sym, best_dist = wp_sym, d
                                        if best_sym:
                                            rt.context["target_market"] = best_sym
                                            rt.context["selling"] = True
                                        else:
                                            for item in inventory:
                                                sym = item.get("symbol")
                                                units = int(item.get("units", 0))
                                                if sym and units > 0:
                                                    try:
                                                        self.navigator.jettison_cargo(ship_symbol, sym, units)
                                                    except Exception:
                                                        pass
                                            ship = self.data_warehouse.ships_by_symbol.get(ship_symbol) or ship
                                            if rt:
                                                rt.context.pop("selling", None)
                                                rt.context.pop("target_market", None)
                                except Exception:
                                    pass
                        except Exception:
                            pass
                # Reset to IDLE for next hop; preserve selling/target when continuing
                if rt:
                    rt.state = ShipState.IDLE
                    rt.context.pop("destination", None)
                    if not rt.context.get("selling"):
                        rt.context.pop("target_market", None)
                return
        except Exception as e:
            logging.error(f"Probe market fetch failed at {target}: {e}")

        # If in transit, just schedule next wakeup and return
        try:
            if ship and ship.nav and ship.nav.status == ShipNavStatus.IN_TRANSIT:
                if rt:
                    rt.state = ShipState.NAVIGATING
                    rt.context["destination"] = "PROBE_MARKET"
                    arrival = ship.nav.route.arrival if ship.nav and ship.nav.route else ""
                    if isinstance(arrival, str) and arrival:
                        rt.next_wakeup_ts = arrival
                    else:
                        from datetime import datetime, timedelta, timezone

                        when = datetime.now(timezone.utc) + timedelta(seconds=10)
                        rt.next_wakeup_ts = when.isoformat(timespec="milliseconds").replace("+00:00", "Z")
                return
        except Exception:
            pass

        # Cross-system travel if needed (non-blocking)
        try:
            target_system = "-".join(target.split("-")[:2]) if isinstance(target, str) else None
            current_system = ship.nav.systemSymbol if ship and ship.nav else None
            if target_system and current_system and target_system != current_system:
                try:
                    ship = self.navigator.warp_to_system(ship_symbol, target_system)
                except Exception:
                    ship = self.navigator.jump_to_system(ship_symbol, target_system)
                # Schedule wakeup based on route arrival if available
                ship = self.data_warehouse.ships_by_symbol.get(ship_symbol) or ship
                if rt:
                    rt.state = ShipState.NAVIGATING
                    rt.context["destination"] = "PROBE_MARKET"
                    try:
                        arrival = ship.nav.route.arrival if ship and ship.nav and ship.nav.route else ""
                        if isinstance(arrival, str) and arrival:
                            rt.next_wakeup_ts = arrival
                        else:
                            from datetime import datetime, timedelta, timezone

                            when = datetime.now(timezone.utc) + timedelta(seconds=10)
                            rt.next_wakeup_ts = when.isoformat(timespec="milliseconds").replace("+00:00", "Z")
                    except Exception:
                        from datetime import datetime, timedelta, timezone

                        when = datetime.now(timezone.utc) + timedelta(seconds=10)
                        rt.next_wakeup_ts = when.isoformat(timespec="milliseconds").replace("+00:00", "Z")
                return
        except Exception as _e:
            logging.error(f"Cross-system navigation failed for {ship_symbol} -> {target}: {_e}")

        # In-system travel (non-blocking)
        role = ship.registration.role if ship and ship.registration else None
        is_miner_selling = bool(role == ShipRole.EXCAVATOR and rt and rt.context.get("selling"))
        if is_miner_selling:
            # Attempt CRUISE then DRIFT on error 4203
            def _attempt_to(target_wp: str, mode: ShipNavFlightMode) -> bool:
                try:
                    self.navigator._ensure_orbit(ship_symbol)
                except Exception:
                    pass
                try:
                    self.navigator._maybe_set_flight_mode(ship_symbol, mode)
                except Exception:
                    pass
                resp = self.client.fleet.navigate_ship(ship_symbol, target_wp)
                if isinstance(resp, dict) and resp.get("error"):
                    err = resp.get("error") or {}
                    code = err.get("code")
                    if code == 4203:
                        data = err.get("data") or {}
                        logging.info(
                            f"Insufficient fuel for {mode.name} to {target_wp}: required={data.get('fuelRequired')} available={data.get('fuelAvailable')}"
                        )
                        return False
                    logging.info(f"Navigate error to {target_wp}: {err}")
                    return False
                # Schedule wakeup after successful navigate
                try:
                    ship2 = self.data_warehouse.ships_by_symbol.get(ship_symbol) or self.navigator._refresh_ship(
                        ship_symbol
                    )
                    if rt:
                        rt.state = ShipState.NAVIGATING
                        rt.context["destination"] = "PROBE_MARKET"
                        arrival2 = ship2.nav.route.arrival if ship2 and ship2.nav and ship2.nav.route else ""
                        if isinstance(arrival2, str) and arrival2:
                            rt.next_wakeup_ts = arrival2
                        else:
                            from datetime import datetime, timedelta, timezone

                            when = datetime.now(timezone.utc) + timedelta(seconds=10)
                            rt.next_wakeup_ts = when.isoformat(timespec="milliseconds").replace("+00:00", "Z")
                except Exception:
                    pass
                return True

            if not _attempt_to(target, ShipNavFlightMode.CRUISE):
                _attempt_to(target, ShipNavFlightMode.DRIFT)
            # Refresh local ship entry minimally
            ship = self.data_warehouse.ships_by_symbol.get(ship_symbol) or ship
            return
        else:
            ship = self.navigator.navigate_in_system(ship_symbol, target)
            # Schedule wakeup and return immediately
            if rt:
                rt.state = ShipState.NAVIGATING
                rt.context["destination"] = "PROBE_MARKET"
                try:
                    arrival = ship.nav.route.arrival if ship and ship.nav and ship.nav.route else ""
                    if isinstance(arrival, str) and arrival:
                        rt.next_wakeup_ts = arrival
                    else:
                        from datetime import datetime, timedelta, timezone

                        when = datetime.now(timezone.utc) + timedelta(seconds=10)
                        rt.next_wakeup_ts = when.isoformat(timespec="milliseconds").replace("+00:00", "Z")
                except Exception:
                    from datetime import datetime, timedelta, timezone

                    when = datetime.now(timezone.utc) + timedelta(seconds=10)
                    rt.next_wakeup_ts = when.isoformat(timespec="milliseconds").replace("+00:00", "Z")
            return

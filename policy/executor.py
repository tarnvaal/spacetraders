import logging

from api.client import ApiClient
from data.enums import ShipAction, ShipRole
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
        closest = self.navigator_algorithms.find_closest_mineable_waypoint(ship_symbol)
        logging.info(f"Closest mineable waypoint: {closest}")
        if not closest:
            return
        ship = self.navigator.navigate_in_system(ship_symbol, closest)
        rt = self.data_warehouse.runtime.get(ship_symbol)
        if rt and ship and ship.nav and ship.nav.route:
            rt.state = ShipState.NAVIGATING
            rt.context["destination"] = "MINE"
        logging.info(f"Navigating to {closest}")

    def _extract_minerals(self, ship_symbol: str) -> None:
        self.navigator.extract_at_current_waypoint(ship_symbol)
        ship = self.data_warehouse.ships_by_symbol.get(ship_symbol)
        rt = self.data_warehouse.runtime.get(ship_symbol)
        if rt and ship and ship.cooldown:
            rt.state = ShipState.MINING

    def _probe_visit_market(self, ship_symbol: str) -> None:
        ship = self.data_warehouse.ships_by_symbol.get(ship_symbol)
        rt = self.data_warehouse.runtime.get(ship_symbol)
        target: str | None = rt.context.get("target_market") if rt else None
        if not target:
            logging.info(f"Probe target not set for {ship_symbol}; skipping.")
            return
        logging.info(f"Probe navigating to market: {target}")
        if rt and ship and ship.nav and ship.nav.route is not None:
            rt.state = ShipState.NAVIGATING
            rt.context["destination"] = "PROBE_MARKET"
        # Cross-system travel if needed
        try:
            target_system = "-".join(target.split("-")[:2]) if isinstance(target, str) else None
            current_system = ship.nav.systemSymbol if ship and ship.nav else None
            if target_system and current_system and target_system != current_system:
                try:
                    ship = self.navigator.warp_to_system(ship_symbol, target_system)
                except Exception:
                    ship = self.navigator.jump_to_system(ship_symbol, target_system)
                ship = self.navigator.wait_until_arrival(ship_symbol)
        except Exception as _e:
            logging.error(f"Cross-system navigation failed for {ship_symbol} -> {target}: {_e}")
        # In-system travel and arrival
        ship = self.navigator.navigate_in_system(ship_symbol, target)
        ship = self.navigator.wait_until_arrival(ship_symbol)
        # Fetch and upsert market snapshot
        try:
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
                                        i.get("symbol") for i in inventory if isinstance(i, dict) and i.get("symbol")
                                    }
                                    current_wp = ship.nav.waypointSymbol if ship and ship.nav else None
                                    best_sym = None
                                    best_dist = None
                                    if current_wp and cargo_syms:
                                        for wp_sym, snapshot in self.data_warehouse.market_prices_by_waypoint.items():
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
        except Exception as e:
            logging.error(f"Probe market fetch failed at {target}: {e}")
        # Reset to IDLE for next hop; preserve selling/target when continuing
        if rt:
            rt.state = ShipState.IDLE
            rt.context.pop("destination", None)
            if not rt.context.get("selling"):
                rt.context.pop("target_market", None)

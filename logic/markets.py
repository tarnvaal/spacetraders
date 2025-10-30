import logging

from api.client import ApiClient
from data.enums import WaypointTraitType
from data.storage import get_storage
from data.warehouse import Warehouse

from .navigation import Navigation


class Markets(Navigation):
    def __init__(self, client: ApiClient, warehouse: Warehouse):
        super().__init__(client, warehouse)

    def refuel_if_available(self, ship_symbol: str, *, units: int | None = None, from_cargo: bool | None = None):
        """
        Dock if needed and refuel if the market offers fuel. Returns refreshed Ship.
        """
        self._ensure_docked(ship_symbol)
        # Attempt refuel; API will error if fuel isn't sold here. Let it propagate.
        resp = self.client.fleet.refuel_ship(ship_symbol, units=units, from_cargo=from_cargo)
        # Log BUY transaction if available
        try:
            import os
            import time

            tx = (resp.get("data") or {}).get("transaction") if isinstance(resp, dict) else None
            agent_after = (resp.get("data") or {}).get("agent") if isinstance(resp, dict) else None
            if isinstance(tx, dict):
                price_per_unit = tx.get("pricePerUnit")
                total_price = tx.get("totalPrice")
                purchased_units = tx.get("units")
                logs_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "logs")
                if not os.path.isdir(logs_dir):
                    os.makedirs(logs_dir, exist_ok=True)
                ship = self._refresh_ship(ship_symbol)
                ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
                with open(os.path.join(logs_dir, "trades.log"), "a", encoding="utf-8") as f:
                    # action ship waypoint symbol units unitPrice totalPrice
                    f.write(
                        f"{ts}\tBUY\t{ship_symbol}\t{ship.nav.waypointSymbol}\tFUEL\t{purchased_units}\t{price_per_unit}\t{total_price}\n"
                    )
                # Update credits in warehouse if present
                try:
                    if isinstance(agent_after, dict) and agent_after.get("credits") is not None:
                        self.warehouse.credits = int(agent_after.get("credits"))
                except Exception:
                    pass
                # Persist transaction in SQLite
                try:
                    credits_after = agent_after.get("credits") if isinstance(agent_after, dict) else None
                    storage = get_storage()
                    storage.insert_transaction(
                        ts=ts,
                        ship=ship_symbol,
                        waypoint=ship.nav.waypointSymbol,
                        action="BUY",
                        symbol="FUEL",
                        units=purchased_units,
                        unit_price=price_per_unit,
                        total_price=total_price,
                        credits_after=credits_after,
                    )
                except Exception:
                    pass
        except Exception:
            pass
        return self._refresh_ship(ship_symbol)

    def find_nearest_marketplace(self, ship_symbol: str, exclude: set[str] | None = None) -> str:
        ship = self._refresh_ship(ship_symbol)
        system_symbol = ship.nav.systemSymbol
        current_wp = ship.nav.waypointSymbol
        payloads = self.client.waypoints.find_waypoints_by_trait(system_symbol, WaypointTraitType.MARKETPLACE)
        if not payloads:
            raise ValueError("No marketplaces found in current system")
        self.warehouse.upsert_waypoints_detail(payloads)
        best_sym = None
        best_dist = None
        for p in payloads:
            sym = p.get("symbol")
            if not sym:
                continue
            if exclude and sym in exclude:
                continue
            dist = self._waypoint_distance(current_wp, sym)
            if best_dist is None or dist < best_dist:
                best_sym, best_dist = sym, dist
        if not best_sym:
            raise ValueError("Unable to select nearest marketplace")
        return best_sym

    def find_best_marketplace_for_cargo(self, ship_symbol: str) -> str:
        """
        Choose the nearest marketplace that can buy at least one item in current cargo.
        Falls back to nearest UNVISITED marketplace if none explicitly accept the cargo; if all
        marketplaces are visited and none accept, falls back to nearest marketplace.
        """
        ship = self._refresh_ship(ship_symbol)
        system_symbol = ship.nav.systemSymbol
        current_wp = ship.nav.waypointSymbol

        cargo_payload = self.client.fleet.get_cargo(ship_symbol)
        inventory = (cargo_payload.get("data") or {}).get("inventory", []) if isinstance(cargo_payload, dict) else []
        cargo_syms = {i.get("symbol") for i in inventory if i.get("symbol")}
        if not cargo_syms:
            return self.find_nearest_marketplace(ship_symbol)

        payloads = self.client.waypoints.find_waypoints_by_trait(system_symbol, WaypointTraitType.MARKETPLACE)
        if not payloads:
            raise ValueError("No marketplaces found in current system")
        self.warehouse.upsert_waypoints_detail(payloads)

        candidates: list[tuple[str, float]] = []
        for p in payloads:
            sym = p.get("symbol")
            if not sym:
                continue
            market = self.client.waypoints.get_market(system_symbol, sym)
            if market:
                self.warehouse.upsert_market_snapshot(system_symbol, market)
            goods = market.get("tradeGoods", []) if isinstance(market, dict) else []
            sellable = {g.get("symbol") for g in goods if g.get("symbol") and g.get("sellPrice", 0) > 0}
            if not (sellable & cargo_syms):
                continue
            dist = self._waypoint_distance(current_wp, sym)
            candidates.append((sym, dist))

        if candidates:
            candidates.sort(key=lambda x: x[1])
            best_sym, best_dist = candidates[0]
            return best_sym

        # Fallback to nearest UNVISITED marketplace
        unvisited: list[tuple[str, float]] = []
        for p in payloads:
            sym = p.get("symbol")
            if not sym:
                continue
            if sym in self.warehouse.market_prices_by_waypoint:
                continue
            dist = self._waypoint_distance(current_wp, sym)
            unvisited.append((sym, dist))
        if unvisited:
            unvisited.sort(key=lambda x: x[1])
            best_sym, best_dist = unvisited[0]
            return best_sym

        # Last resort: nearest marketplace
        return self.find_nearest_marketplace(ship_symbol)

    def find_nearest_unvisited_marketplace(self, ship_symbol: str, exclude: set[str] | None = None) -> str | None:
        ship = self._refresh_ship(ship_symbol)
        system_symbol = ship.nav.systemSymbol
        current_wp = ship.nav.waypointSymbol
        payloads = self.client.waypoints.find_waypoints_by_trait(system_symbol, WaypointTraitType.MARKETPLACE)
        if not payloads:
            return None
        self.warehouse.upsert_waypoints_detail(payloads)
        best_sym = None
        best_dist = None
        for p in payloads:
            sym = p.get("symbol")
            if not sym or sym in self.warehouse.market_prices_by_waypoint:
                continue
            if exclude and sym in exclude:
                continue
            dist = self._waypoint_distance(current_wp, sym)
            if best_dist is None or dist < best_dist:
                best_sym, best_dist = sym, dist
        return best_sym

    def dock_and_sell_all_cargo(self, ship_symbol: str, market_wp_symbol: str):
        ship = self._refresh_ship(ship_symbol)
        if ship.nav.waypointSymbol != market_wp_symbol:
            ship = self.navigate_in_system(ship_symbol, market_wp_symbol)
            ship = self.wait_until_arrival(ship_symbol)
        ship = self._ensure_docked(ship_symbol)
        # Determine what this market accepts; upsert market snapshot
        market = self.client.waypoints.get_market(ship.nav.systemSymbol, market_wp_symbol)
        goods = market.get("tradeGoods", []) if isinstance(market, dict) else []
        if market:
            try:
                self.warehouse.upsert_market_snapshot(ship.nav.systemSymbol, market)
                for good in goods:
                    self.warehouse.record_good_observation(ship.nav.systemSymbol, market_wp_symbol, good)
            except Exception:
                pass
        sellable = {g.get("symbol") for g in goods if g.get("symbol") and g.get("sellPrice", 0) > 0}
        cargo_payload = self.client.fleet.get_cargo(ship_symbol)
        inventory = (cargo_payload.get("data") or {}).get("inventory", []) if isinstance(cargo_payload, dict) else []
        if not inventory:
            pass
        total_credits = 0
        for item in list(inventory):
            sym = item.get("symbol")
            units = item.get("units", 0)
            if not sym or not units:
                continue
            if sym not in sellable:
                continue
            tx = self.client.fleet.sell(ship_symbol, sym, units)
            if isinstance(tx, dict) and tx.get("error"):
                continue
            data_obj = tx.get("data") if isinstance(tx, dict) else None
            transaction = data_obj.get("transaction") if isinstance(data_obj, dict) else None
            agent_after = data_obj.get("agent") if isinstance(data_obj, dict) else None
            total_price = transaction.get("totalPrice") if isinstance(transaction, dict) else None
            price_per_unit = transaction.get("pricePerUnit") if isinstance(transaction, dict) else None
            credits_after = agent_after.get("credits") if isinstance(agent_after, dict) else None
            if total_price is not None:
                total_credits += total_price
                # Console log sale details
                try:
                    wp = ship.nav.waypointSymbol if ship and ship.nav else market_wp_symbol
                    if credits_after is not None:
                        # Sync warehouse credits when provided
                        try:
                            self.warehouse.credits = int(credits_after)
                        except Exception:
                            pass
                        logging.info(
                            f"Sold {units}x {sym} at {wp}: unit={price_per_unit} total={total_price} credits={credits_after}"
                        )
                    else:
                        logging.info(f"Sold {units}x {sym} at {wp}: unit={price_per_unit} total={total_price}")
                except Exception:
                    pass
            # Persist transaction in SQLite
            try:
                import time as _t

                ts = _t.strftime("%Y-%m-%dT%H:%M:%SZ", _t.gmtime())
                storage = get_storage()
                storage.insert_transaction(
                    ts=ts,
                    ship=ship_symbol,
                    waypoint=ship.nav.waypointSymbol if ship and ship.nav else market_wp_symbol,
                    action="SELL",
                    symbol=sym,
                    units=units,
                    unit_price=price_per_unit,
                    total_price=total_price,
                    credits_after=credits_after,
                )
            except Exception:
                pass
                # append SELL log line
                try:
                    import os
                    import time

                    logs_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "logs")
                    if not os.path.isdir(logs_dir):
                        os.makedirs(logs_dir, exist_ok=True)
                    ship = self._refresh_ship(ship_symbol)
                    ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
                    with open(os.path.join(logs_dir, "trades.log"), "a", encoding="utf-8") as f:
                        # action ship waypoint symbol units unitPrice totalPrice
                        f.write(
                            f"{ts}\tSELL\t{ship_symbol}\t{ship.nav.waypointSymbol}\t{sym}\t{units}\t{price_per_unit}\t{total_price}\n"
                        )
                except Exception:
                    pass
            # Refresh ship cargo state after each sale
            self._refresh_ship(ship_symbol)
        # Refuel if possible and not full
        ship = self._refresh_ship(ship_symbol)
        if ship.fuel.current < ship.fuel.capacity:
            try:
                ship = self.refuel_if_available(ship_symbol)
            except Exception:
                pass
        ship = self._ensure_orbit(ship_symbol)
        return ship

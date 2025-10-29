from api.client import ApiClient
from data.warehouse import Warehouse
from data.enums import WaypointTraitType
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
            import os, time
            tx = (resp.get('data') or {}).get('transaction') if isinstance(resp, dict) else None
            if isinstance(tx, dict):
                price_per_unit = tx.get('pricePerUnit')
                total_price = tx.get('totalPrice')
                purchased_units = tx.get('units')
                logs_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "logs")
                if not os.path.isdir(logs_dir):
                    os.makedirs(logs_dir, exist_ok=True)
                ship = self._refresh_ship(ship_symbol)
                ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
                with open(os.path.join(logs_dir, "trades.log"), "a", encoding="utf-8") as f:
                    # action ship waypoint symbol units unitPrice totalPrice
                    f.write(f"{ts}\tBUY\t{ship_symbol}\t{ship.nav.waypointSymbol}\tFUEL\t{purchased_units}\t{price_per_unit}\t{total_price}\n")
        except Exception:
            pass
        return self._refresh_ship(ship_symbol)

    def find_nearest_marketplace(self, ship_symbol: str) -> str:
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
            sym = p.get('symbol')
            if not sym:
                continue
            dist = self._waypoint_distance(current_wp, sym)
            if best_dist is None or dist < best_dist:
                best_sym, best_dist = sym, dist
        if not best_sym:
            raise ValueError("Unable to select nearest marketplace")
        try:
            print(f"[Trade] Nearest marketplace: {best_sym} ({best_dist:.1f} units)")
        except Exception:
            print(f"[Trade] Nearest marketplace: {best_sym}")
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
        inventory = (cargo_payload.get('data') or {}).get('inventory', []) if isinstance(cargo_payload, dict) else []
        cargo_syms = {i.get('symbol') for i in inventory if i.get('symbol')}
        if not cargo_syms:
            return self.find_nearest_marketplace(ship_symbol)

        payloads = self.client.waypoints.find_waypoints_by_trait(system_symbol, WaypointTraitType.MARKETPLACE)
        if not payloads:
            raise ValueError("No marketplaces found in current system")
        self.warehouse.upsert_waypoints_detail(payloads)

        candidates: list[tuple[str, float]] = []
        for p in payloads:
            sym = p.get('symbol')
            if not sym:
                continue
            market = self.client.waypoints.get_market(system_symbol, sym)
            if market:
                self.warehouse.upsert_market_snapshot(system_symbol, market)
            goods = market.get('tradeGoods', []) if isinstance(market, dict) else []
            sellable = {g.get('symbol') for g in goods if g.get('symbol') and g.get('sellPrice', 0) > 0}
            if not (sellable & cargo_syms):
                continue
            dist = self._waypoint_distance(current_wp, sym)
            candidates.append((sym, dist))

        if candidates:
            candidates.sort(key=lambda x: x[1])
            best_sym, best_dist = candidates[0]
            try:
                print(f"[Trade] Best marketplace for cargo: {best_sym} ({best_dist:.1f} units)")
            except Exception:
                print(f"[Trade] Best marketplace for cargo: {best_sym}")
            return best_sym

        # Fallback to nearest UNVISITED marketplace
        unvisited: list[tuple[str, float]] = []
        for p in payloads:
            sym = p.get('symbol')
            if not sym:
                continue
            if sym in self.warehouse.market_prices_by_waypoint:
                continue
            dist = self._waypoint_distance(current_wp, sym)
            unvisited.append((sym, dist))
        if unvisited:
            unvisited.sort(key=lambda x: x[1])
            best_sym, best_dist = unvisited[0]
            try:
                print(f"[Trade] No known buyers; mapping unvisited marketplace {best_sym} ({best_dist:.1f} units)")
            except Exception:
                print(f"[Trade] No known buyers; mapping unvisited marketplace {best_sym}")
            return best_sym

        # Last resort: nearest marketplace
        return self.find_nearest_marketplace(ship_symbol)

    def find_nearest_unvisited_marketplace(self, ship_symbol: str) -> str | None:
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
            sym = p.get('symbol')
            if not sym or sym in self.warehouse.market_prices_by_waypoint:
                continue
            dist = self._waypoint_distance(current_wp, sym)
            if best_dist is None or dist < best_dist:
                best_sym, best_dist = sym, dist
        return best_sym

    def dock_and_sell_all_cargo(self, ship_symbol: str, market_wp_symbol: str):
        ship = self._refresh_ship(ship_symbol)
        if ship.nav.waypointSymbol != market_wp_symbol:
            ship = self.navigate_in_system(ship_symbol, market_wp_symbol)
            print(f"[Nav] Waiting for {ship_symbol} to arrive at {market_wp_symbol}...")
            ship = self.wait_until_arrival(ship_symbol)
        ship = self._ensure_docked(ship_symbol)
        # Determine what this market accepts; upsert market snapshot
        market = self.client.waypoints.get_market(ship.nav.systemSymbol, market_wp_symbol)
        goods = market.get('tradeGoods', []) if isinstance(market, dict) else []
        if market:
            try:
                self.warehouse.upsert_market_snapshot(ship.nav.systemSymbol, market)
                for good in goods:
                    self.warehouse.record_good_observation(ship.nav.systemSymbol, market_wp_symbol, good)
            except Exception:
                pass
        sellable = {g.get('symbol') for g in goods if g.get('symbol') and g.get('sellPrice', 0) > 0}
        cargo_payload = self.client.fleet.get_cargo(ship_symbol)
        inventory = (cargo_payload.get('data') or {}).get('inventory', []) if isinstance(cargo_payload, dict) else []
        if not inventory:
            print("[Trade] No cargo to sell")
        total_credits = 0
        for item in list(inventory):
            sym = item.get('symbol')
            units = item.get('units', 0)
            if not sym or not units:
                continue
            if sym not in sellable:
                print(f"[Trade] Cannot sell {sym} here; skipping")
                continue
            print(f"[Trade] Selling {units}x {sym}...")
            tx = self.client.fleet.sell(ship_symbol, sym, units)
            if isinstance(tx, dict) and tx.get('error'):
                err = tx.get('error', {})
                print(f"[Trade] Sell failed for {sym}: {err.get('message', 'unknown error')}")
                continue
            transaction = (tx.get('data') or {}).get('transaction') if isinstance(tx, dict) else None
            total_price = transaction.get('totalPrice') if isinstance(transaction, dict) else None
            price_per_unit = transaction.get('pricePerUnit') if isinstance(transaction, dict) else None
            if total_price is not None:
                total_credits += total_price
                print(f"[Trade] Sold {units}x {sym} for {total_price} credits")
                # append SELL log line
                try:
                    import os, time
                    logs_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "logs")
                    if not os.path.isdir(logs_dir):
                        os.makedirs(logs_dir, exist_ok=True)
                    ship = self._refresh_ship(ship_symbol)
                    ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
                    with open(os.path.join(logs_dir, "trades.log"), "a", encoding="utf-8") as f:
                        # action ship waypoint symbol units unitPrice totalPrice
                        f.write(f"{ts}\tSELL\t{ship_symbol}\t{ship.nav.waypointSymbol}\t{sym}\t{units}\t{price_per_unit}\t{total_price}\n")
                except Exception:
                    pass
            # Refresh ship cargo state after each sale
            self._refresh_ship(ship_symbol)
        # Refuel if possible and not full
        ship = self._refresh_ship(ship_symbol)
        if ship.fuel.current < ship.fuel.capacity:
            try:
                print("[Trade] Refueling (if available)...")
                ship = self.refuel_if_available(ship_symbol)
            except Exception:
                print("[Trade] Refuel unavailable at this marketplace")
        ship = self._ensure_orbit(ship_symbol)
        print(f"[Trade] Selling complete. +{total_credits} credits")
        return ship



from api.client import ApiClient
from data.enums import WaypointTraitType
from data.warehouse import Warehouse

from .navigation import Navigation


class NavigationAlgorithms(Navigation):
    def __init__(self, client: ApiClient, warehouse: Warehouse):
        super().__init__(client, warehouse)

    def find_closest_mineable_waypoint(self, ship_symbol: str, traits: list[WaypointTraitType] | None = None) -> str:
        """
        Find the closest waypoint in the current system that has a mineable trait.
        Returns the waypoint symbol.
        """
        if traits is None:
            traits = [
                WaypointTraitType.MINERAL_DEPOSITS,
                WaypointTraitType.COMMON_METAL_DEPOSITS,
                WaypointTraitType.PRECIOUS_METAL_DEPOSITS,
                WaypointTraitType.RARE_METAL_DEPOSITS,
                WaypointTraitType.METHANE_POOLS,
                WaypointTraitType.ICE_CRYSTALS,
                WaypointTraitType.EXPLOSIVE_GASES,
            ]

        ship = self._refresh_ship(ship_symbol)
        system_symbol = ship.nav.systemSymbol
        current_wp_symbol = ship.nav.waypointSymbol

        # Ensure current waypoint coordinates are known (fetch if missing)
        current_ref = self.warehouse.waypoints_by_symbol.get(current_wp_symbol)
        if not current_ref:
            detail = self.client.waypoints.get(system_symbol, current_wp_symbol)
            if detail:
                self.warehouse.upsert_waypoint_detail(detail)
                current_ref = self.warehouse.waypoints_by_symbol.get(current_wp_symbol)
        if not current_ref:
            raise ValueError(f"Unknown current waypoint in warehouse: {current_wp_symbol}")

        # Query candidates by trait and upsert into warehouse for coordinate access
        seen: dict[str, dict] = {}
        for trait in traits:
            payloads = self.client.waypoints.find_waypoints_by_trait(system_symbol, trait)
            for p in payloads:
                sym = p.get("symbol") if isinstance(p, dict) else None
                if sym and sym != current_wp_symbol and sym not in seen:
                    seen[sym] = p
        if not seen:
            raise ValueError("No mineable waypoints found in current system")

        # Persist details for coordinate lookup if needed
        self.warehouse.upsert_waypoints_detail(list(seen.values()))

        # Compute distances and choose closest
        best_sym = None
        best_dist = None
        for sym, p in seen.items():
            # Prefer coordinates from payload; fallback to warehouse refs
            px = p.get("x") if isinstance(p, dict) else None
            py = p.get("y") if isinstance(p, dict) else None
            if px is None or py is None:
                ref = self.warehouse.waypoints_by_symbol.get(sym)
                if not ref:
                    continue
                px, py = ref.x, ref.y
            dist = self._distance_hypot(current_ref.x, current_ref.y, px, py)
            if best_dist is None or dist < best_dist:
                best_dist = dist
                best_sym = sym
        if not best_sym:
            raise ValueError("Unable to determine closest mineable waypoint")
        return best_sym

    def find_closest_refuel_waypoint(self, ship_symbol: str) -> str:
        """
        Find the closest waypoint in the current system that supports refueling.
        Current heuristic: waypoints with MARKETPLACE trait.
        Returns the waypoint symbol.
        """
        ship = self._refresh_ship(ship_symbol)
        system_symbol = ship.nav.systemSymbol
        current_wp_symbol = ship.nav.waypointSymbol

        # Ensure current waypoint coordinates are known (fetch if missing)
        current_ref = self.warehouse.waypoints_by_symbol.get(current_wp_symbol)
        if not current_ref:
            detail = self.client.waypoints.get(system_symbol, current_wp_symbol)
            if detail:
                self.warehouse.upsert_waypoint_detail(detail)
                current_ref = self.warehouse.waypoints_by_symbol.get(current_wp_symbol)
        if not current_ref:
            raise ValueError(f"Unknown current waypoint in warehouse: {current_wp_symbol}")

        # Helper to decide if a stored market snapshot indicates fuel is purchasable
        def _snapshot_sells_fuel(snapshot: dict | None) -> bool:
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

        # If the current station sells fuel, prefer it immediately
        current_snapshot = self.warehouse.market_prices_by_waypoint.get(current_wp_symbol)
        if _snapshot_sells_fuel(current_snapshot):
            return current_wp_symbol

        # If unknown for current station, fetch market once to decide
        if current_snapshot is None:
            market = self.client.waypoints.get_market(system_symbol, current_wp_symbol)
            if isinstance(market, dict):
                self.warehouse.upsert_market_snapshot(system_symbol, market)
                if _snapshot_sells_fuel(self.warehouse.market_prices_by_waypoint.get(current_wp_symbol)):
                    return current_wp_symbol

        # Query candidates by trait and upsert into warehouse for coordinate access
        seen: dict[str, dict] = {}
        payloads = self.client.waypoints.find_waypoints_by_trait(system_symbol, WaypointTraitType.MARKETPLACE)
        for p in payloads:
            sym = p.get("symbol") if isinstance(p, dict) else None
            if not sym or sym == current_wp_symbol or sym in seen:
                continue
            # Exclude marketplaces that we already know do NOT sell fuel
            snapshot = self.warehouse.market_prices_by_waypoint.get(sym)
            if snapshot is not None and not _snapshot_sells_fuel(snapshot):
                continue
            seen[sym] = p
        if not seen:
            raise ValueError("No refuel-capable waypoints (MARKETPLACE) found in current system")

        # Persist details for coordinate lookup if needed
        self.warehouse.upsert_waypoints_detail(list(seen.values()))

        # Compute distances and choose closest
        best_sym = None
        best_dist = None
        for sym, p in seen.items():
            px = p.get("x") if isinstance(p, dict) else None
            py = p.get("y") if isinstance(p, dict) else None
            if px is None or py is None:
                ref = self.warehouse.waypoints_by_symbol.get(sym)
                if not ref:
                    continue
                px, py = ref.x, ref.y
            dist = self._distance_hypot(current_ref.x, current_ref.y, px, py)
            if best_dist is None or dist < best_dist:
                best_dist = dist
                best_sym = sym
        if not best_sym:
            raise ValueError("Unable to determine closest refuel waypoint")
        return best_sym

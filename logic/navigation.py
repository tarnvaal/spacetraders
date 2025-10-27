import time
import math
from api.client import ApiClient
from data.warehouse import Warehouse
from data.enums import ShipNavFlightMode, ShipNavStatus, WaypointTraitType


class navigation():
    def __init__(self, client: ApiClient, warehouse: Warehouse):
        self.client = client
        self.warehouse = warehouse

    def navigate_in_system(self, ship_symbol: str, waypoint_symbol: str, flight_mode: ShipNavFlightMode | None = None):
        """
        Navigate a ship within its current system to a target waypoint.
        Ensures orbit, optionally sets flight mode, then navigates.
        Returns the refreshed Ship model from the warehouse.
        """
        self._refresh_ship(ship_symbol)
        # Avoid self-navigation no-ops
        current = self.warehouse.ships_by_symbol.get(ship_symbol)
        if current and current.nav and current.nav.waypointSymbol == waypoint_symbol:
            print(f"[Nav] {ship_symbol} already at {waypoint_symbol}; skipping navigation")
            return current
        self._ensure_orbit(ship_symbol)
        if flight_mode is not None:
            self._maybe_set_flight_mode(ship_symbol, flight_mode)
        print(f"[Nav] Navigating {ship_symbol} to {waypoint_symbol}...")
        self.client.fleet.navigate_ship(ship_symbol, waypoint_symbol)
        return self._refresh_ship(ship_symbol)

    def jump_to_system(self, ship_symbol: str, system_symbol: str):
        """
        Jump a ship to another system. Ensures ship is in orbit first.
        Returns the refreshed Ship model from the warehouse.
        """
        self._refresh_ship(ship_symbol)
        self._ensure_orbit(ship_symbol)
        self.client.fleet.jump_ship(ship_symbol, system_symbol)
        return self._refresh_ship(ship_symbol)

    def warp_to_system(self, ship_symbol: str, system_symbol: str):
        """
        Warp a ship to another system (requires warp drive). Ensures orbit.
        Returns the refreshed Ship model from the warehouse.
        """
        self._refresh_ship(ship_symbol)
        self._ensure_orbit(ship_symbol)
        self.client.fleet.warp_ship(ship_symbol, system_symbol)
        return self._refresh_ship(ship_symbol)

    def wait_until_arrival(self, ship_symbol: str, poll_interval_s: int = 5, timeout_s: int | None = None):
        """
        Poll until the ship is no longer IN_TRANSIT. Returns the final Ship.
        Raises TimeoutError if timeout_s is set and exceeded.
        """
        start = time.time()
        # Pre-departure: allow brief time for status to flip to IN_TRANSIT after navigate
        pre_deadline = start + 10
        while True:
            ship = self._refresh_ship(ship_symbol)
            if ship.nav.status == ShipNavStatus.IN_TRANSIT:
                break
            # If destination differs from current waypoint, we might be mid-transition; keep polling briefly
            route = ship.nav.route
            if route and route.destination and route.destination.symbol and ship.nav.waypointSymbol != route.destination.symbol:
                # still about to depart or instant-hop; keep polling
                pass
            else:
                # Not in transit and no meaningful route; nothing to wait for
                return ship
            if timeout_s is not None and (time.time() - start) >= timeout_s:
                raise TimeoutError(f"wait_until_arrival timed out for {ship_symbol} (pre-departure)")
            if time.time() > pre_deadline:
                # Give up waiting for departure; return current state
                return ship
            time.sleep(max(1, poll_interval_s))

        # In transit: wait until arrival
        while True:
            ship = self._refresh_ship(ship_symbol)
            if ship.nav.status != ShipNavStatus.IN_TRANSIT:
                return ship
            if timeout_s is not None and (time.time() - start) >= timeout_s:
                raise TimeoutError(f"wait_until_arrival timed out for {ship_symbol}")
            time.sleep(max(1, poll_interval_s))

    # Internal helpers
    def _get_ship_dict(self, ship_symbol: str) -> dict:
        payload = self.client.fleet.get_ship(ship_symbol)
        if isinstance(payload, dict):
            return payload.get('data', payload)
        return {}

    def _refresh_ship(self, ship_symbol: str):
        ship_dict = self._get_ship_dict(ship_symbol)
        return self.warehouse.upsert_ship(ship_dict)

    def _ensure_orbit(self, ship_symbol: str):
        ship = self._refresh_ship(ship_symbol)
        if ship.nav.status == ShipNavStatus.DOCKED:
            self.client.fleet.orbit_ship(ship_symbol)
            ship = self._refresh_ship(ship_symbol)
        return ship

    def _ensure_docked(self, ship_symbol: str):
        ship = self._refresh_ship(ship_symbol)
        if ship.nav.status == ShipNavStatus.IN_ORBIT:
            self.client.fleet.dock_ship(ship_symbol)
            ship = self._refresh_ship(ship_symbol)
        return ship

    def _maybe_set_flight_mode(self, ship_symbol: str, mode: ShipNavFlightMode):
        ship = self._refresh_ship(ship_symbol)
        if ship.nav.flightMode != mode:
            self.client.fleet.set_flight_mode(ship_symbol, mode)
            ship = self._refresh_ship(ship_symbol)
        return ship

    # Convenience actions
    def refuel_if_available(self, ship_symbol: str, *, units: int | None = None, from_cargo: bool | None = None):
        """
        Dock if needed and refuel if the market offers fuel. Returns refreshed Ship.
        """
        self._ensure_docked(ship_symbol)
        # Attempt refuel; API will error if fuel isn't sold here. Let it propagate.
        self.client.fleet.refuel_ship(ship_symbol, units=units, from_cargo=from_cargo)
        return self._refresh_ship(ship_symbol)

    def extract_at_current_waypoint(self, ship_symbol: str):
        """
        Ensure orbit and request extraction. Returns dict response from API; does not alter cargo here beyond refresh.
        """
        self._ensure_orbit(ship_symbol)
        resp = self.client.fleet.extract(ship_symbol)
        # Optionally refresh cargo state
        self._refresh_ship(ship_symbol)
        return resp

    def jettison_cargo(self, ship_symbol: str, symbol: str, units: int):
        """
        Jettison specified cargo units. Returns dict response from API; refreshes ship state.
        """
        resp = self.client.fleet.jettison(ship_symbol, symbol, units)
        self._refresh_ship(ship_symbol)
        return resp

    # Mining and trading helpers
    def mine_until_full(self, ship_symbol: str):
        """Continuously extract at current waypoint until cargo is full, respecting cooldowns."""
        while True:
            ship = self._refresh_ship(ship_symbol)
            if ship.cargo.units >= ship.cargo.capacity:
                print(f"[Mine] Cargo full ({ship.cargo.units}/{ship.cargo.capacity})")
                return ship
            self._ensure_orbit(ship_symbol)
            print("[Mine] Extracting...")
            resp = self.extract_at_current_waypoint(ship_symbol)
            extraction = (resp.get('data') or {}).get('extraction') if isinstance(resp, dict) else None
            if extraction:
                yield_sym = (extraction.get('yield') or {}).get('symbol')
                yield_units = (extraction.get('yield') or {}).get('units')
                print(f"[Mine] Yield: {yield_units}x {yield_sym}")
            ship = self._refresh_ship(ship_symbol)
            rem = ship.cooldown.remainingSeconds
            if rem and rem > 0:
                print(f"[Mine] Cooldown {rem}s...")
                time.sleep(rem)
            else:
                time.sleep(1)

    def _waypoint_distance(self, a_symbol: str, b_symbol: str) -> float:
        a = self.warehouse.waypoints_by_symbol.get(a_symbol)
        b = self.warehouse.waypoints_by_symbol.get(b_symbol)
        if not a or not b:
            return float('inf')
        return self._distance_hypot(a.x, a.y, b.x, b.y)

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
        print(f"[Trade] Nearest marketplace: {best_sym} ({best_dist:.1f} units)")
        return best_sym

    def dock_and_sell_all_cargo(self, ship_symbol: str, market_wp_symbol: str):
        ship = self._refresh_ship(ship_symbol)
        if ship.nav.waypointSymbol != market_wp_symbol:
            ship = self.navigate_in_system(ship_symbol, market_wp_symbol)
            print(f"[Nav] Waiting for {ship_symbol} to arrive at {market_wp_symbol}...")
            ship = self.wait_until_arrival(ship_symbol)
        ship = self._ensure_docked(ship_symbol)
        cargo_payload = self.client.fleet.get_cargo(ship_symbol)
        inventory = (cargo_payload.get('data') or {}).get('inventory', []) if isinstance(cargo_payload, dict) else []
        if not inventory:
            print("[Trade] No cargo to sell")
        total_credits = 0
        for item in inventory:
            sym = item.get('symbol')
            units = item.get('units', 0)
            if not sym or not units:
                continue
            print(f"[Trade] Selling {units}x {sym}...")
            tx = self.client.fleet.sell(ship_symbol, sym, units)
            total_price = ((tx.get('data') or {}).get('transaction') or {}).get('totalPrice') if isinstance(tx, dict) else None
            if total_price is not None:
                total_credits += total_price
                print(f"[Trade] Sold {units}x {sym} for {total_price} credits")
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

    def quickstart_mine_until_full_and_sell(self, ship_symbol: str, *, set_mode: ShipNavFlightMode | None = None):
        print(f"[Quickstart] Starting mine-until-full-and-sell for {ship_symbol}...")
        # Go to closest mineable node
        ship = self.navigate_to_closest_mineable(ship_symbol, set_mode=set_mode)
        # Refuel if not full
        ship = self._refresh_ship(ship_symbol)
        if ship.fuel.current < ship.fuel.capacity:
            try:
                print("[Quickstart] Refueling before mining (if available)...")
                ship = self.refuel_if_available(ship_symbol)
            except Exception:
                print("[Quickstart] Refuel unavailable at mining waypoint")
        # Mine until full
        self.mine_until_full(ship_symbol)
        # Sell at nearest marketplace
        market_wp = self.find_nearest_marketplace(ship_symbol)
        self.dock_and_sell_all_cargo(ship_symbol, market_wp)
        return self._refresh_ship(ship_symbol)

    # Targeting helpers
    def _distance_hypot(self, ax: int, ay: int, bx: int, by: int) -> float:
        dx = ax - bx
        dy = ay - by
        return math.hypot(dx, dy)

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
        if best_dist is not None:
            try:
                print(f"[Target] Closest mineable waypoint: {best_sym} ({best_dist:.1f} units)")
            except Exception:
                print(f"[Target] Closest mineable waypoint: {best_sym}")
        return best_sym

    def navigate_to_closest_mineable(self, ship_symbol: str, *, set_mode: ShipNavFlightMode | None = None, poll_interval_s: int = 5, timeout_s: int | None = None):
        target = self.find_closest_mineable_waypoint(ship_symbol)
        ship = self.navigate_in_system(ship_symbol, target, flight_mode=set_mode)
        print(f"[Nav] Waiting for {ship_symbol} to arrive at {target}...")
        ship = self.wait_until_arrival(ship_symbol, poll_interval_s=poll_interval_s, timeout_s=timeout_s)
        return ship

    def quickstart_mine_flow(self, ship_symbol: str, target_waypoint_symbol: str, *, set_mode: ShipNavFlightMode | None = None, poll_interval_s: int = 5, timeout_s: int | None = None):
        """
        Navigate to an asteroid, wait for arrival, dock/refuel if available, orbit, and extract once.
        Returns a tuple: (final_ship_model, extract_response_dict)
        """
        print(f"[Quickstart] Starting mining flow for {ship_symbol}...")
        # Auto-select closest mineable if target is placeholder or same as current
        placeholder_values = {None, "", "WAYPOINT-SYMBOL", "REPLACE_WITH_ENGINEERED_ASTEROID"}
        current = self._refresh_ship(ship_symbol)
        if target_waypoint_symbol in placeholder_values or target_waypoint_symbol == current.nav.waypointSymbol:
            print("[Quickstart] Auto-selecting closest mineable waypoint")
            ship = self.navigate_to_closest_mineable(ship_symbol, set_mode=set_mode, poll_interval_s=poll_interval_s, timeout_s=timeout_s)
        else:
            print(f"[Quickstart] Using configured target: {target_waypoint_symbol}")
            ship = self.navigate_in_system(ship_symbol, target_waypoint_symbol, flight_mode=set_mode)
            print(f"[Nav] Waiting for {ship_symbol} to arrive at {target_waypoint_symbol}...")
            ship = self.wait_until_arrival(ship_symbol, poll_interval_s=poll_interval_s, timeout_s=timeout_s)
        try:
            print("[Quickstart] Attempting refuel (if available)...")
            ship = self.refuel_if_available(ship_symbol)
        except Exception:
            # fuel not available here; continue
            print("[Quickstart] Refuel unavailable at this waypoint")
        ship = self._ensure_orbit(ship_symbol)
        print("[Quickstart] Extracting resources...")
        extract_resp = self.extract_at_current_waypoint(ship_symbol)
        return ship, extract_resp



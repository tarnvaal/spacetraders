"""
Navigation module for ship movement, mining operations, and trading workflows.
Handles waypoint navigation, cargo management, and automated mining cycles.
"""

import math
import time

from api.client import ApiClient
from data.enums import ShipNavFlightMode, ShipNavStatus, WaypointTraitType
from data.warehouse import Warehouse


class Navigation:
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
            return current
        self._ensure_orbit(ship_symbol)
        if flight_mode is not None:
            self._maybe_set_flight_mode(ship_symbol, flight_mode)
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
            if (
                route
                and route.destination
                and route.destination.symbol
                and ship.nav.waypointSymbol != route.destination.symbol
            ):
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
                # On arrival, upsert waypoint detail if missing
                try:
                    wp = ship.nav.waypointSymbol
                    sys = ship.nav.systemSymbol
                    if wp and sys and wp not in self.warehouse.full_waypoints_by_symbol:
                        detail = self.client.waypoints.get(sys, wp)
                        if detail:
                            self.warehouse.upsert_waypoint_detail(detail)
                except Exception:
                    pass
                return ship
            if timeout_s is not None and (time.time() - start) >= timeout_s:
                raise TimeoutError(f"wait_until_arrival timed out for {ship_symbol}")
            time.sleep(max(1, poll_interval_s))

    # Internal helpers
    def _get_ship_dict(self, ship_symbol: str) -> dict:
        payload = self.client.fleet.get_ship(ship_symbol)
        if isinstance(payload, dict):
            return payload.get("data", payload)
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

    def refuel(self, ship_symbol: str):
        """
        Refuel at the current waypoint.
        """
        # Ensure docked then refuel
        self._ensure_docked(ship_symbol)
        # Max fuel is the capacity of the ship
        ship = self._refresh_ship(ship_symbol)
        units = ship.fuel.capacity - ship.fuel.current
        if units > 0:
            self.client.fleet.refuel_ship(ship_symbol, units=units, from_cargo=True)
        return self._refresh_ship(ship_symbol)

    # Mining helpers removed

    def _waypoint_distance(self, a_symbol: str, b_symbol: str) -> float:
        a = self.warehouse.waypoints_by_symbol.get(a_symbol)
        b = self.warehouse.waypoints_by_symbol.get(b_symbol)
        if not a or not b:
            return float("inf")
        return self._distance_hypot(a.x, a.y, b.x, b.y)

    # Market helpers moved to logic/markets.py

    def _waypoint_has_trait(self, waypoint_symbol: str, trait: WaypointTraitType) -> bool:
        """Check if a waypoint has a given trait; fetch detail if missing."""
        full = self.warehouse.full_waypoints_by_symbol.get(waypoint_symbol)
        if not full:
            # Try to fetch from API using any known system (infer from symbol prefix)
            system_symbol = "-".join(waypoint_symbol.split("-")[:2])
            detail = self.client.waypoints.get(system_symbol, waypoint_symbol)
            if detail:
                self.warehouse.upsert_waypoint_detail(detail)
                full = self.warehouse.full_waypoints_by_symbol.get(waypoint_symbol)
        if not full:
            return False
        return any(t.symbol == trait.value for t in full.traits)

    # Selling flow moved to logic/markets.py

    # Quickstart flows removed

    # Targeting helpers
    def _distance_hypot(self, ax: int, ay: int, bx: int, by: int) -> float:
        dx = ax - bx
        dy = ay - by
        return math.hypot(dx, dy)

    # Targeting algorithms moved to logic/navigation_algorithms.py

    # Navigation flow helpers removed

    # Quickstart flows removed

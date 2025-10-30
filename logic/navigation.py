"""
Navigation module for ship movement, mining operations, and trading workflows.
Handles waypoint navigation, cargo management, and automated mining cycles.
"""

import math
import time
from datetime import datetime, timezone

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
        # Avoid eager GET; prefer cached ship when available
        current = self.warehouse.ships_by_symbol.get(ship_symbol) or self._refresh_ship(ship_symbol)
        if current and current.nav and current.nav.waypointSymbol == waypoint_symbol:
            return current
        self._ensure_orbit(ship_symbol)
        if flight_mode is not None:
            self._maybe_set_flight_mode(ship_symbol, flight_mode)
        resp = self.client.fleet.navigate_ship(ship_symbol, waypoint_symbol)
        # Apply POST response to cached ship to avoid immediate GET
        # Prefer cached ship; API response applied below keeps it up-to-date
        ship = self.warehouse.ships_by_symbol.get(ship_symbol) or self._refresh_ship(ship_symbol)
        try:
            data_obj = resp.get("data") if isinstance(resp, dict) else None
            nav_obj = data_obj.get("nav") if isinstance(data_obj, dict) else None
            fuel_obj = data_obj.get("fuel") if isinstance(data_obj, dict) else None
            if isinstance(nav_obj, dict) and ship and ship.nav:
                # Update nav status, waypoint, route
                status_val = nav_obj.get("status")
                if isinstance(status_val, str):
                    try:
                        from data.enums import ShipNavStatus

                        ship.nav.status = ShipNavStatus(status_val)
                    except Exception:
                        pass
                ship.nav.systemSymbol = nav_obj.get("systemSymbol", ship.nav.systemSymbol)
                ship.nav.waypointSymbol = nav_obj.get("waypointSymbol", ship.nav.waypointSymbol)
                route_dict = nav_obj.get("route") or {}
                if isinstance(route_dict, dict) and ship.nav.route:
                    # Destination and times
                    dest = route_dict.get("destination") or {}
                    if isinstance(dest, dict) and ship.nav.route.destination:
                        ship.nav.route.destination.symbol = dest.get("symbol")
                        ship.nav.route.destination.systemSymbol = dest.get("systemSymbol")
                        ship.nav.route.destination.x = dest.get("x")
                        ship.nav.route.destination.y = dest.get("y")
                    origin = route_dict.get("origin") or {}
                    if isinstance(origin, dict) and ship.nav.route.departure:
                        ship.nav.route.departure.symbol = origin.get("symbol")
                        ship.nav.route.departure.systemSymbol = origin.get("systemSymbol")
                        ship.nav.route.departure.x = origin.get("x")
                        ship.nav.route.departure.y = origin.get("y")
                    ship.nav.route.departureTime = route_dict.get("departureTime", ship.nav.route.departureTime)
                    ship.nav.route.arrival = route_dict.get("arrival", ship.nav.route.arrival)
                    ship.nav.route.distance = route_dict.get("distance", ship.nav.route.distance)
            if isinstance(fuel_obj, dict) and ship and ship.fuel:
                ship.fuel.current = fuel_obj.get("current", ship.fuel.current)
                ship.fuel.capacity = fuel_obj.get("capacity", ship.fuel.capacity)
        except Exception:
            pass
        try:
            arrival = ship.nav.route.arrival if ship and ship.nav and ship.nav.route else ""
            status = ship.nav.status if ship and ship.nav else None
            current_wp = ship.nav.waypointSymbol if ship and ship.nav else None
            dest_wp = (
                ship.nav.route.destination.symbol
                if ship and ship.nav and ship.nav.route and ship.nav.route.destination
                else None
            )
            from_wp = (
                ship.nav.route.departure.symbol
                if ship and ship.nav and ship.nav.route and ship.nav.route.departure
                else None
            )
            import logging

            logging.debug(
                f"navigate_in_system[{ship_symbol}]: from={from_wp} to={dest_wp} now_at={current_wp} status={status} arrival={arrival}"
            )
        except Exception:
            pass
        return ship

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
            # Back off slightly to reduce churn
            time.sleep(max(2, poll_interval_s))

        # In transit: wait until arrival, using ETA-based sleeping when available
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
            # If we know the arrival time, sleep closer to ETA to reduce GETs
            try:
                arrival_iso = ship.nav.route.arrival if ship and ship.nav and ship.nav.route else None
                if isinstance(arrival_iso, str) and arrival_iso:
                    iso = arrival_iso[:-1] + "+00:00" if arrival_iso.endswith("Z") else arrival_iso
                    eta = datetime.fromisoformat(iso)
                    now = datetime.now(timezone.utc)
                    wait_s = max(1.0, (eta - now).total_seconds() - 0.5)
                    # Cap to a reasonable interval
                    time.sleep(min(max(2.0, wait_s), 30.0))
                    continue
            except Exception:
                pass
            time.sleep(max(2, poll_interval_s))

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
        ship = self.warehouse.ships_by_symbol.get(ship_symbol) or self._refresh_ship(ship_symbol)
        if ship.nav.status == ShipNavStatus.DOCKED:
            resp = self.client.fleet.orbit_ship(ship_symbol)
            # Apply nav status from POST response
            try:
                data_obj = resp.get("data") if isinstance(resp, dict) else None
                nav_obj = data_obj.get("nav") if isinstance(data_obj, dict) else None
                if isinstance(nav_obj, dict):
                    status_val = nav_obj.get("status")
                    if isinstance(status_val, str):
                        from data.enums import ShipNavStatus as _NavStatus

                        ship.nav.status = _NavStatus(status_val)
            except Exception:
                pass
        return ship

    def _ensure_docked(self, ship_symbol: str):
        ship = self.warehouse.ships_by_symbol.get(ship_symbol) or self._refresh_ship(ship_symbol)
        if ship.nav.status == ShipNavStatus.IN_ORBIT:
            resp = self.client.fleet.dock_ship(ship_symbol)
            # Apply nav status from POST response
            try:
                data_obj = resp.get("data") if isinstance(resp, dict) else None
                nav_obj = data_obj.get("nav") if isinstance(data_obj, dict) else None
                if isinstance(nav_obj, dict):
                    status_val = nav_obj.get("status")
                    if isinstance(status_val, str):
                        from data.enums import ShipNavStatus as _NavStatus

                        ship.nav.status = _NavStatus(status_val)
            except Exception:
                pass
        return ship

    def _maybe_set_flight_mode(self, ship_symbol: str, mode: ShipNavFlightMode):
        ship = self.warehouse.ships_by_symbol.get(ship_symbol) or self._refresh_ship(ship_symbol)
        if ship.nav.flightMode != mode:
            resp = self.client.fleet.set_flight_mode(ship_symbol, mode)
            try:
                data_obj = resp.get("data") if isinstance(resp, dict) else None
                nav_obj = data_obj.get("nav") if isinstance(data_obj, dict) else None
                fm = (nav_obj.get("flightMode") if isinstance(nav_obj, dict) else None) or mode.value
                from data.enums import ShipNavFlightMode as _FM

                ship.nav.flightMode = _FM(fm) if isinstance(fm, str) else mode
            except Exception:
                ship.nav.flightMode = mode
        return ship

    # Convenience actions

    def extract_at_current_waypoint(self, ship_symbol: str):
        """
        Ensure orbit and request extraction. Returns dict response from API; does not alter cargo here beyond refresh.
        """
        self._ensure_orbit(ship_symbol)
        resp = self.client.fleet.extract(ship_symbol)
        # Apply cooldown and cargo updates from POST response to reduce GETs
        ship = self.warehouse.ships_by_symbol.get(ship_symbol) or self._refresh_ship(ship_symbol)
        try:
            data_obj = resp.get("data") if isinstance(resp, dict) else None
            cooldown = data_obj.get("cooldown") if isinstance(data_obj, dict) else None
            cargo = data_obj.get("cargo") if isinstance(data_obj, dict) else None
            if isinstance(cooldown, dict) and ship and ship.cooldown:
                ship.cooldown.totalSeconds = cooldown.get("totalSeconds", ship.cooldown.totalSeconds)
                ship.cooldown.remainingSeconds = cooldown.get("remainingSeconds", ship.cooldown.remainingSeconds)
                ship.cooldown.expiration = cooldown.get("expiration", ship.cooldown.expiration)
            if isinstance(cargo, dict) and ship and ship.cargo:
                ship.cargo.capacity = cargo.get("capacity", ship.cargo.capacity)
                ship.cargo.units = cargo.get("units", ship.cargo.units)
        except Exception:
            pass
        try:
            import logging

            cooldown = ship.cooldown.expiration if ship and ship.cooldown else ""
            logging.debug(f"extract_at_current_waypoint[{ship_symbol}]: cooldown.expiration={cooldown}")
        except Exception:
            pass
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
            resp = self.client.fleet.refuel_ship(ship_symbol, units=units, from_cargo=True)
            try:
                data_obj = resp.get("data") if isinstance(resp, dict) else None
                fuel_obj = data_obj.get("fuel") if isinstance(data_obj, dict) else None
                if isinstance(fuel_obj, dict) and ship and ship.fuel:
                    ship.fuel.current = fuel_obj.get("current", ship.fuel.current)
                    ship.fuel.capacity = fuel_obj.get("capacity", ship.fuel.capacity)
            except Exception:
                pass
        try:
            import logging

            logging.debug(f"refuel[{ship_symbol}]: fuel now {ship.fuel.current}/{ship.fuel.capacity}")
        except Exception:
            pass
        return ship

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

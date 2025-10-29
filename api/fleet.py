"""
Fleet API module for ship control operations including navigation, extraction, and trading.
"""

from typing import TYPE_CHECKING

from data.enums import ShipNavFlightMode

if TYPE_CHECKING:
    from api.client import ApiClient


class FleetAPI:
    """Fleet endpoints."""

    def __init__(self, client: "ApiClient"):
        self.client = client

    def get_my_ships(self, page: int | None = None, limit: int | None = None) -> dict:
        """Fetch fleet list (GET /my/ships) with optional pagination."""
        params: dict = {}
        if page is not None:
            params["page"] = page
        if limit is not None:
            params["limit"] = limit
        return self.client.http.get_json("my/ships", self.client.agent_key, params=(params or None))

    def get_ship(self, ship_symbol: str) -> dict:
        """Fetch a single ship (GET /my/ships/{shipSymbol})."""
        return self.client.http.get_json(f"my/ships/{ship_symbol}", self.client.agent_key)

    def orbit_ship(self, ship_symbol: str) -> dict:
        """Orbit a ship (POST /my/ships/{shipSymbol}/orbit)."""
        return self.client.http.post_json(f"my/ships/{ship_symbol}/orbit", self.client.agent_key)

    def dock_ship(self, ship_symbol: str) -> dict:
        """Dock a ship (POST /my/ships/{shipSymbol}/dock)."""
        return self.client.http.post_json(f"my/ships/{ship_symbol}/dock", self.client.agent_key)

    def navigate_ship(self, ship_symbol: str, waypoint_symbol: str) -> dict:
        """Navigate a ship to a waypoint (POST /my/ships/{shipSymbol}/navigate)."""
        body = {"waypointSymbol": waypoint_symbol}
        return self.client.http.post_json(f"my/ships/{ship_symbol}/navigate", self.client.agent_key, json=body)

    def set_flight_mode(self, ship_symbol: str, mode: ShipNavFlightMode) -> dict:
        """Set ship flight mode (PATCH /my/ships/{shipSymbol}/nav)."""
        body = {"flightMode": mode.value}
        return self.client.http.patch_json(f"my/ships/{ship_symbol}/nav", self.client.agent_key, json=body)

    def refuel_ship(self, ship_symbol: str, units: int | None = None, from_cargo: bool | None = None) -> dict:
        """Refuel a ship (POST /my/ships/{shipSymbol}/refuel)."""
        body: dict = {}
        if units is not None:
            body["units"] = units
        if from_cargo is not None:
            body["fromCargo"] = from_cargo
        return self.client.http.post_json(f"my/ships/{ship_symbol}/refuel", self.client.agent_key, json=(body or None))

    def warp_ship(self, ship_symbol: str, system_symbol: str) -> dict:
        """Warp to a system (POST /my/ships/{shipSymbol}/warp)."""
        body = {"systemSymbol": system_symbol}
        return self.client.http.post_json(f"my/ships/{ship_symbol}/warp", self.client.agent_key, json=body)

    def jump_ship(self, ship_symbol: str, system_symbol: str) -> dict:
        """Jump to a system (POST /my/ships/{shipSymbol}/jump)."""
        body = {"systemSymbol": system_symbol}
        return self.client.http.post_json(f"my/ships/{ship_symbol}/jump", self.client.agent_key, json=body)

    def extract(self, ship_symbol: str) -> dict:
        """Extract resources (POST /my/ships/{shipSymbol}/extract)."""
        return self.client.http.post_json(f"my/ships/{ship_symbol}/extract", self.client.agent_key)

    def jettison(self, ship_symbol: str, symbol: str, units: int) -> dict:
        """Jettison cargo (POST /my/ships/{shipSymbol}/jettison)."""
        body = {"symbol": symbol, "units": units}
        return self.client.http.post_json(f"my/ships/{ship_symbol}/jettison", self.client.agent_key, json=body)

    def get_cargo(self, ship_symbol: str) -> dict:
        """Get ship cargo (GET /my/ships/{shipSymbol}/cargo)."""
        return self.client.http.get_json(f"my/ships/{ship_symbol}/cargo", self.client.agent_key)

    def sell(self, ship_symbol: str, symbol: str, units: int) -> dict:
        """Sell cargo (POST /my/ships/{shipSymbol}/sell)."""
        body = {"symbol": symbol, "units": units}
        return self.client.http.post_json(f"my/ships/{ship_symbol}/sell", self.client.agent_key, json=body)

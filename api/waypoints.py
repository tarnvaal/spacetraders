from typing import Dict, Any, List, Optional
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from api.client import ApiClient


class WaypointsAPI:
    """Waypoints endpoints."""

    def __init__(self, client: 'ApiClient'):
        self.client = client

    def list(self, system_symbol: str, *, page: int = 1, limit: int = 20) -> List[Dict[str, Any]]:
        """
        Fetch a page of waypoints for a system.
        GET /v2/systems/{systemSymbol}/waypoints
        Returns the 'data' array from the response.
        """
        query = {"page": page, "limit": limit}
        payload = self.client.http.get_json(
            f"systems/{system_symbol}/waypoints",
            self.client.agent_key,
            params=query,
        )
        return payload.get("data", []) if isinstance(payload, dict) else []

    def get(self, system_symbol: str, waypoint_symbol: str) -> Optional[Dict[str, Any]]:
        """
        Fetch waypoint details for a single waypoint.
        GET /v2/systems/{systemSymbol}/waypoints/{waypointSymbol}
        Returns the 'data' object from the response.
        """
        payload = self.client.http.get_json(
            f"systems/{system_symbol}/waypoints/{waypoint_symbol}",
            self.client.agent_key,
        )
        if isinstance(payload, dict):
            return payload.get("data")
        return None



from typing import Dict, Any, List, Optional
from urllib.parse import urlencode
from api.handle_requests import get_json


def list_waypoints(system_symbol: str, agent_key: str, *, page: int = 1, limit: int = 20) -> List[Dict[str, Any]]:
    """
    Fetch a page of waypoints for a system.
    GET /v2/systems/{systemSymbol}/waypoints
    Returns the 'data' array from the response.
    """
    query = {"page": page, "limit": limit}
    payload = get_json(f"systems/{system_symbol}/waypoints", agent_key, params=query)
    return payload.get("data", []) if isinstance(payload, dict) else []


def get_waypoint(system_symbol: str, waypoint_symbol: str, agent_key: str) -> Optional[Dict[str, Any]]:
    """
    Fetch waypoint details for a single waypoint.
    GET /v2/systems/{systemSymbol}/waypoints/{waypointSymbol}
    Returns the 'data' object from the response.
    """
    payload = get_json(f"systems/{system_symbol}/waypoints/{waypoint_symbol}", agent_key)
    if isinstance(payload, dict):
        return payload.get("data")
    return None



"""
API Client module providing centralized access to SpaceTraders API endpoints.
Orchestrates sub-API modules for agent, systems, waypoints, and fleet operations.
"""

from api.agent import AgentAPI
from api.fleet import FleetAPI
from api.handle_requests import RequestHandler
from api.systems import SystemsAPI
from api.waypoints import WaypointsAPI


class ApiClient:
    """Root client that centralizes sub-APIs and holds shared HTTP/session state."""

    def __init__(self, agent_key: str, api_url: str = "https://api.spacetraders.io/v2"):
        self.agent_key = agent_key
        self.http = RequestHandler(api_url)
        self.agent = AgentAPI(self)
        self.systems = SystemsAPI(self)
        self.waypoints = WaypointsAPI(self)
        self.fleet = FleetAPI(self)

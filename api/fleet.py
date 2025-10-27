from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from api.client import ApiClient

class FleetAPI:
    """Fleet endpoints."""

    def __init__(self, client: 'ApiClient'):
        self.client = client

    def get(self) -> dict:
        """Fetch fleet list (GET /my/ships)."""
        return self.client.http.get_json("my/ships", self.client.agent_key)
    
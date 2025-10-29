"""
Systems API module for accessing star system information and metadata.
"""
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from api.client import ApiClient

class SystemsAPI:
    """Systems endpoints."""

    def __init__(self, client: 'ApiClient'):
        self.client = client

    def get(self) -> dict:
        """Fetch systems list (GET /systems)."""
        return self.client.http.get_json("systems", self.client.agent_key)
"""
Agent API module for accessing player account information and agent details.
"""
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from api.client import ApiClient

class AgentAPI:
    """Agent endpoints."""

    def __init__(self, client: 'ApiClient'):
        self.client = client

    def get(self) -> dict:
        """Fetch current agent details (GET /my/agent)."""
        return self.client.http.get_json("my/agent", self.client.agent_key)
    

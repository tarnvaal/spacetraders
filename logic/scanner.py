"""
Scanner module for discovering and mapping systems, waypoints, ships, and markets.
Handles initial fleet and system reconnaissance operations.
"""

from api.client import ApiClient
from data.enums import WaypointTraitType
from data.warehouse import Warehouse


class Scanner:
    def __init__(self, client: ApiClient, warehouse: Warehouse):
        self.client = client
        self.warehouse = warehouse
        self.hq_system = ""
        agent_data = self.client.agent.get()["data"]
        for key, value in agent_data.items():
            setattr(self.warehouse, key, value)
        self.hq_system = "-".join(agent_data["headquarters"].split("-")[:2])

    def get_credits(self):
        return self.warehouse.credits

    def scan_systems(self):
        systems_api = self.client.systems
        systems_payload = systems_api.get()["data"]
        self.warehouse.upsert_systems(systems_payload)

    def scan_waypoints_by_type(self, waypoint_type: WaypointTraitType):
        waypoints_api = self.client.waypoints
        waypoints_payload = waypoints_api.find_waypoints_by_trait(self.hq_system, waypoint_type)
        self.warehouse.upsert_waypoints_detail(waypoints_payload)

    def scan_fleet(self, pages: int = 1, limit: int | None = None, all_pages: bool = False):
        """Scan and upsert fleet, supporting pagination.
        By default scans a single page. Use pages>1 for a fixed count, or set all_pages=True to fetch all.
        """
        total_loaded = 0
        current_page = 1
        requested_pages = max(1, pages)

        while True:
            payload = self.client.fleet.get_my_ships(page=current_page, limit=limit)
            loaded = self.warehouse.upsert_fleet(payload)
            total_loaded += len(loaded)

            meta = payload.get("meta", {}) if isinstance(payload, dict) else {}
            data_len = len(payload.get("data", []) or []) if isinstance(payload, dict) else 0

            if not all_pages and current_page >= requested_pages:
                break

            # Determine if there's another page
            next_page_exists = False
            total_items = meta.get("total")
            meta_limit = meta.get("limit") or limit
            meta_page = meta.get("page") or current_page
            if isinstance(total_items, int) and isinstance(meta_limit, int) and meta_limit > 0:
                # Compute total pages and compare
                total_pages = (total_items + meta_limit - 1) // meta_limit
                next_page_exists = meta_page < total_pages
            else:
                # Fallback: if fewer items than requested limit, assume no more pages
                if isinstance(meta_limit, int):
                    next_page_exists = data_len >= meta_limit
                else:
                    # Unknown limit -> continue until we hit an empty page
                    next_page_exists = data_len > 0

            if not next_page_exists:
                break

            current_page += 1

    def print_fleet(self):
        fleet = self.client.fleet.get_my_ships()

        for _ in fleet.get("data", []):
            pass

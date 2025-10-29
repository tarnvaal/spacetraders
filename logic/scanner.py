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
        loaded_systems = self.warehouse.upsert_systems(systems_payload)
        print(f"Populated {len(loaded_systems)} systems")

    def scan_waypoints_by_type(self, waypoint_type: WaypointTraitType):
        waypoints_api = self.client.waypoints
        waypoints_payload = waypoints_api.find_waypoints_by_trait(self.hq_system, waypoint_type)
        loaded_waypoints = self.warehouse.upsert_waypoints_detail(waypoints_payload)
        print(f"Populated {len(loaded_waypoints)} waypoints of type {waypoint_type.value}")

    def print_waypoints_by_type(self, waypoint_type: WaypointTraitType):
        print(f"Printing {waypoint_type.value} waypoints...")
        for waypoint in self.warehouse.full_waypoints_by_symbol.values():
            matched_trait = next((t for t in waypoint.traits if t.symbol == waypoint_type.value), None)
            if matched_trait:
                print(f"    Waypoint: {waypoint.symbol} ({waypoint.type}) ({waypoint.x}, {waypoint.y})")
                print(
                    f"        Trait: {matched_trait.symbol}"
                    + (f" - {matched_trait.name}" if matched_trait.name else "")
                )
                if waypoint_type == WaypointTraitType.SHIPYARD:
                    available_ships = self.client.waypoints.find_waypoint_available_ships(
                        self.hq_system, waypoint.symbol
                    )
                    for shipType in available_ships.get("shipTypes", []):
                        print(f"            {shipType['type']}")

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

        print(f"Populated {total_loaded} fleet")

    def print_fleet(self):
        fleet = self.client.fleet.get_my_ships()

        for ship in fleet.get("data", []):
            print(f"Ship: {ship['symbol']}")
            print(f"    Type: {ship['registration']['role']}")
            if ship.get("fuel", {}).get("capacity", 0) > 0:
                print(f"    Fuel: {ship['fuel'].get('current', 0)} / {ship['fuel'].get('capacity', 0)}")
            print(f"    Location: {ship.get('nav', {}).get('waypointSymbol')}")
            nav = ship.get("nav", {})
            route = nav.get("route", {})
            origin = route.get("origin", {})
            destination = route.get("destination", {})
            print(
                f"    Nav: {nav.get('status')} @ {nav.get('systemSymbol')}/{nav.get('waypointSymbol')} [{nav.get('flightMode', 'CRUISE')}]"
            )
            if route:
                print(f"        Route: {origin.get('symbol', '?')} -> {destination.get('symbol', '?')}")
                if "departureTime" in route and "arrival" in route:
                    print(f"        Times: depart {route['departureTime']} arrive {route['arrival']}")
            engine = ship.get("engine", {})
            if engine:
                speed = engine.get("speed", "?")
                print(f"    Engine: {engine.get('symbol', '?')} (speed {speed})")
            cargo = ship.get("cargo", {})
            if cargo.get("capacity", 0) > 0:
                print(f"    Cargo: {cargo.get('units', 0)} / {cargo.get('capacity', 0)}")
            cooldown = ship.get("cooldown", {})
            if cooldown.get("totalSeconds", 0) > 0:
                print(f"    Cooldown: {cooldown.get('remainingSeconds', 0)} / {cooldown.get('totalSeconds', 0)}")

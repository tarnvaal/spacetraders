from api.client import ApiClient
from data.warehouse import Warehouse
from data.enums import WaypointTraitType

class scanner():
    def __init__(self, client: ApiClient, warehouse: Warehouse):
        self.client = client
        self.warehouse = warehouse
        self.hq_system = ""
        agent_data = self.client.agent.get()['data']
        for key, value in agent_data.items():
            setattr(self.warehouse, key, value)
        self.hq_system = "-".join((agent_data['headquarters'].split("-")[:2]))
        
    def print_hq_system(self):
        print(f"HQ system: {self.hq_system}")
        
    def scan_systems(self):
        systems_api = self.client.systems
        systems_payload = systems_api.get()['data']
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
                print(f"        Trait: {matched_trait.symbol}" + (f" - {matched_trait.name}" if matched_trait.name else ""))
                if waypoint_type == WaypointTraitType.SHIPYARD:
                    available_ships = self.client.waypoints.find_waypoint_available_ships(self.hq_system, waypoint.symbol)
                    for shipType in available_ships.get('shipTypes', []):
                        print(f"            {shipType['type']}")
                        
    def scan_fleet(self):
        return self.client.fleet.get()

    def print_fleet(self):
        fleet = self.client.fleet.get()
        for ship in fleet.get('data', []):
            print(f"Ship: {ship['symbol']}")
            print(f"    Type: {ship['registration']['role']}")
            if ship.get('fuel', {}).get('capacity', 0) > 0:
                print(f"    Fuel: {ship['fuel'].get('current', 0)} / {ship['fuel'].get('capacity', 0)}")
            print(f"    Location: {ship.get('nav', {}).get('waypointSymbol')}")
            nav = ship.get('nav', {})
            route = nav.get('route', {})
            origin = route.get('origin', {})
            destination = route.get('destination', {})
            print(f"    Nav: {nav.get('status')} @ {nav.get('systemSymbol')}/{nav.get('waypointSymbol')} [{nav.get('flightMode', 'CRUISE')}]")
            if route:
                print(f"        Route: {origin.get('symbol', '?')} -> {destination.get('symbol', '?')}")
                if 'departureTime' in route and 'arrival' in route:
                    print(f"        Times: depart {route['departureTime']} arrive {route['arrival']}")
            engine = ship.get('engine', {})
            if engine:
                speed = engine.get('speed', '?')
                print(f"    Engine: {engine.get('symbol', '?')} (speed {speed})")
            cargo = ship.get('cargo', {})
            if cargo.get('capacity', 0) > 0:
                print(f"    Cargo: {cargo.get('units', 0)} / {cargo.get('capacity', 0)}")
            cooldown = ship.get('cooldown', {})
            if cooldown.get('totalSeconds', 0) > 0:
                print(f"    Cooldown: {cooldown.get('remainingSeconds', 0)} / {cooldown.get('totalSeconds', 0)}")
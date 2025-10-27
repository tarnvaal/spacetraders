from dotenv import load_dotenv
import os

from api.client import ApiClient
from data.warehouse import Warehouse
from data.enums import WaypointTraitType

# load environment variables
load_dotenv()

#create an api instance to hold the key for all api calls
client = ApiClient(os.getenv("AGENT_TOKEN"))
agent_data = client.agent.get()['data']

# Create a warehouse instance
dataWarehouse = Warehouse()

for key, value in agent_data.items():
    setattr(dataWarehouse, key, value)
    

print(dataWarehouse)

systems_api = client.systems
systems_payload = systems_api.get()['data']
loaded_systems = dataWarehouse.upsert_systems(systems_payload)
print(f"Populated {len(loaded_systems)} systems")

if dataWarehouse.headquarters and "-" in dataWarehouse.headquarters:
    hq_system = dataWarehouse.headquarters.split("-")[0] + "-" + dataWarehouse.headquarters.split("-")[1]
    details = client.waypoints.list(hq_system, page=1, limit=20)
    if details:
        dataWarehouse.upsert_waypoints_detail(details)
        print(f"Populated {len(details)} waypoints for system {hq_system}")

print("Finding shipyards...")
shipyards = client.waypoints.find_waypoints_by_trait(hq_system, WaypointTraitType.SHIPYARD)
dataWarehouse.upsert_waypoints_detail(shipyards)

for waypoint in dataWarehouse.full_waypoints_by_symbol.values():
    if any(t.symbol == WaypointTraitType.SHIPYARD.value for t in waypoint.traits):
        print(f"Shipyard: {waypoint.symbol}")
        print(f"    Type: {waypoint.type}")
        print(f"    Coords: {waypoint.x}, {waypoint.y}")
        available_ships = client.waypoints.find_waypoint_available_ships(hq_system, waypoint.symbol)
        for shipType in available_ships['shipTypes']:
            print(f"        {shipType['type']}")
            
fleet = client.fleet.get()
for ship in fleet['data']:
    print(f"Ship: {ship['symbol']}")
    print(f"    Type: {ship['registration']['role']}")
    if ship['fuel']['capacity'] > 0:
        print(f"    Fuel: {ship['fuel']['current']} / {ship['fuel']['capacity']}")
    print(f"    Location: {ship['nav']['waypointSymbol']}")
    nav = ship['nav']
    route = nav.get('route', {})
    origin = route.get('origin', {})
    destination = route.get('destination', {})
    print(f"    Nav: {nav['status']} @ {nav['systemSymbol']}/{nav['waypointSymbol']} [{nav.get('flightMode', 'CRUISE')}]")
    if route:
        print(f"        Route: {origin.get('symbol', '?')} -> {destination.get('symbol', '?')}")
        if 'departureTime' in route and 'arrival' in route:
            print(f"        Times: depart {route['departureTime']} arrive {route['arrival']}")
    engine = ship.get('engine', {})
    if engine:
        speed = engine.get('speed', '?')
        print(f"    Engine: {engine.get('symbol', '?')} (speed {speed})")
    cargo = ship.get('cargo', {})
    if cargo.get('capacity') > 0:
        print(f"    Cargo: {cargo.get('units', 0)} / {cargo.get('capacity', 0)}")
    cooldown = ship.get('cooldown', {})
    if cooldown.get('totalSeconds') > 0:
        print(f"    Cooldown: {cooldown.get('remainingSeconds', 0)} / {cooldown.get('totalSeconds', 0)}") 
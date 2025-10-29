"""
Mine module for basic mining ship operations and fleet status display.
"""
from api.client import ApiClient
from data.warehouse import Warehouse
from data.enums import WaypointTraitType, ShipRole

class Mine():
    def __init__(self, client: ApiClient, warehouse: Warehouse):
        self.client = client
        self.warehouse = warehouse

    def mine(self):
        print("Mining excavators starting...")
        self.print_fleet()

    def print_fleet(self):
        for ship in self.warehouse.ships_by_symbol.values():
            if ship.registration and ship.registration.role == ShipRole.EXCAVATOR:
                print(
                    f"Mining Ship:{ship.symbol}\n"
                    f"  Role:{ship.registration.role}\n"
                    f"  Fuel:{ship.fuel.current} / {ship.fuel.capacity}\n"
                    f"  Location:{ship.nav.waypointSymbol}\n"
                    f"  Nav:{ship.nav.status} @ {ship.nav.systemSymbol}/{ship.nav.waypointSymbol}\n"
                    f"  Flight Mode: {ship.nav.flightMode}\n"
                    f"  Route: {ship.nav.route.departure.symbol}\n"
                    f"         {ship.nav.route.destination.symbol}\n"
                    f"  Times: depart {ship.nav.route.departureTime}\n"
                    f"         arrive {ship.nav.route.arrival}\n"
                    f"  Engine: {ship.engine.symbol} (speed {ship.engine.speed})\n"
                    f"  Cargo: {ship.cargo.units} / {ship.cargo.capacity}\n"
                    f"  Cooldown: {ship.cooldown.remainingSeconds} / {ship.cooldown.totalSeconds}"
                )
                
    
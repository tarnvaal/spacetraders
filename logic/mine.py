"""
Mine module for basic mining ship operations and fleet status display.
"""

from api.client import ApiClient
from data.enums import ShipRole
from data.warehouse import Warehouse


class Mine:
    def __init__(self, client: ApiClient, warehouse: Warehouse):
        self.client = client
        self.warehouse = warehouse

    def mine(self):
        self.print_fleet()

    def print_fleet(self):
        for ship in self.warehouse.ships_by_symbol.values():
            if ship.registration and ship.registration.role == ShipRole.EXCAVATOR:
                pass

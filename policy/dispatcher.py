import logging

from data.enums import ShipAction
from data.warehouse import Warehouse
from flow.queue import MinHeap
from logic.scanner import Scanner
from logic.utility import get_utc_timestamp


class Dispatcher:
    def __init__(self, warehouse: Warehouse, scanner: Scanner, event_queue: MinHeap):
        self.warehouse = warehouse
        self.scanner = scanner
        self.event_queue = event_queue

    def update_fleet(self):
        self.scanner.scan_fleet(all_pages=True)
        logging.info(f"Fleet updated. {len(self.warehouse.ships_by_symbol)} ships found.")

    def shipReadiness(self, symbol: str):
        ship = self.warehouse.ships_by_symbol.get(symbol)
        arrival = ship.nav.route.arrival
        cooldown = ship.cooldown.expiration
        current = get_utc_timestamp()
        priority = max(arrival, cooldown, current)
        return priority

    def decide_next_action(self, symbol: str) -> ShipAction:
        ship = self.warehouse.ships_by_symbol.get(symbol)
        if ship is None:
            return ShipAction.NOOP

        # Policy: exactly one action; prioritize refueling if not full.
        if ship.fuel.current < ship.fuel.capacity:
            return ShipAction.REFUEL

        # Future policy can route excavators to mining here.
        # if ship.registration.role == ShipRole.EXCAVATOR:
        #     return ShipAction.NAVIGATE_TO_MINE

        return ShipAction.NOOP

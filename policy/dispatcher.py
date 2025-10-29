import logging

from data.warehouse import Warehouse
from flow.queue import MinHeap
from logic.scanner import Scanner


class Dispatcher:
    def __init__(self, warehouse: Warehouse, scanner: Scanner, event_queue: MinHeap):
        self.warehouse = warehouse
        self.scanner = scanner
        self.event_queue = event_queue

    def update_fleet(self):
        self.scanner.scan_fleet(all_pages=True)
        logging.info(f"Fleet updated. {len(self.warehouse.ships_by_symbol)} ships found.")

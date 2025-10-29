from data.warehouse import Warehouse
from data.enums import ShipRole, ShipNavStatus
from logic.scanner import Scanner
from flow.queue import MinHeap

class Dispatcher:
    def __init__(self, warehouse: Warehouse, scanner: Scanner):
        self.warehouse = warehouse
        self.scanner = scanner
        self.ship_queue = []
        self.marketplaces = {}
        
    def fill_ship_queue(self):
        self.scanner.scan_fleet(all_pages=True)

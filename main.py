from dotenv import load_dotenv
import os
import configparser

from api.client import ApiClient
from data.warehouse import Warehouse
from data.enums import WaypointTraitType
from logic.scanner import scanner
from logic.mine import mine
from logic.navigation import navigation

# load environment variables
load_dotenv()

#create an api instance to hold the key for all api calls
client = ApiClient(os.getenv("AGENT_TOKEN"))
dataWarehouse = Warehouse()  
scanner = scanner(client, dataWarehouse)
navigator = navigation(client, dataWarehouse)

# load optional config.ini
config = configparser.ConfigParser()
config_path = os.path.join(os.path.dirname(__file__), "config.ini")
if os.path.exists(config_path):
    config.read(config_path)

scan_shipyards = config.getboolean("scanner", "scan_shipyards", fallback=False) if config.has_section("scanner") else False
print_shipyards = config.getboolean("scanner", "print_shipyards", fallback=False) if config.has_section("scanner") else False
print_fleet = config.getboolean("scanner", "print_fleet", fallback=False) if config.has_section("scanner") else False
do_quickstart_mine = config.getboolean("navigation", "quickstart_mine", fallback=False) if config.has_section("navigation") else False

scanner.print_hq_system()
scanner.scan_systems()
if scan_shipyards:
    scanner.scan_waypoints_by_type(WaypointTraitType.SHIPYARD)
if print_shipyards:
    scanner.print_waypoints_by_type(WaypointTraitType.SHIPYARD)
scanner.scan_fleet()
if print_fleet:
    scanner.print_fleet()
dataWarehouse.print_warehouse_size()

mine = mine(client, dataWarehouse)
mine.mine()
if do_quickstart_mine:
    # Mine until full and sell flow
    ship_symbol = config.get("navigation", "ship_symbol", fallback="SHIP-SYMBOL") if config.has_section("navigation") else "SHIP-SYMBOL"
    ship = navigator.quickstart_mine_until_full_and_sell(ship_symbol)
    print(f"Done: {(ship.nav.status.value if ship.nav.status else '?')} @ {ship.nav.systemSymbol}/{ship.nav.waypointSymbol} | Cargo {ship.cargo.units}/{ship.cargo.capacity}")

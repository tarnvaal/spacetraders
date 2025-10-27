from dotenv import load_dotenv
import os

from api.client import ApiClient
from data.warehouse import Warehouse
from data.enums import WaypointTraitType
from logic.scanner import scanner

# load environment variables
load_dotenv()

#create an api instance to hold the key for all api calls
client = ApiClient(os.getenv("AGENT_TOKEN"))
dataWarehouse = Warehouse()  
scanner = scanner(client, dataWarehouse)
scanner.print_hq_system()
#scanner.scan_systems()
#scanner.scan_waypoints_by_type(WaypointTraitType.SHIPYARD)
#scanner.print_waypoints_by_type(WaypointTraitType.SHIPYARD)
scanner.scan_fleet()
scanner.print_fleet()
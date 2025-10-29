import logging
import os
import sys

from dotenv import load_dotenv

from api.client import ApiClient
from data.enums import ShipRole
from data.warehouse import Warehouse
from flow.queue import MinHeap
from logic.navigation import Navigation
from logic.navigation_algorithms import NavigationAlgorithms
from logic.scanner import Scanner
from policy.dispatcher import Dispatcher

# load environment variables
load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

# Validate required environment variables
agent_token = os.getenv("AGENT_TOKEN")
if not agent_token:
    print("Error: AGENT_TOKEN not found in environment.", file=sys.stderr)
    print("Please set AGENT_TOKEN in your .env file or environment.", file=sys.stderr)
    sys.exit(1)

logging.info("Systems initializing")

# create an api instance to hold the key for all api calls
client = ApiClient(agent_token)
dataWarehouse = Warehouse()
scanner = Scanner(client, dataWarehouse)
navigator = Navigation(client, dataWarehouse)
navigatorAlgorithms = NavigationAlgorithms(client, dataWarehouse)

logging.info("All systems operational.")
credits = scanner.get_credits()
logging.info(f"Credits: {credits}")

event_queue = MinHeap()
dispatcher = Dispatcher(dataWarehouse, scanner, event_queue)
dispatcher.update_fleet()

for ship in dataWarehouse.ships_by_symbol.values():
    logging.info(f"Ship: {ship.symbol} - Readiness: {dispatcher.shipReadiness(ship.symbol)}")

    # send the excavators to the closest mineable waypoint
    if ship.registration.role == ShipRole.EXCAVATOR:
        closest_mineable_waypoint = navigatorAlgorithms.find_closest_mineable_waypoint(ship.symbol)
        logging.info(f"Closest mineable waypoint: {closest_mineable_waypoint}")
        navigator.navigate_in_system(ship.symbol, closest_mineable_waypoint)
        logging.info(f"Navigating to {closest_mineable_waypoint}")
        logging.info(f"Ship: {ship.symbol} - Readiness: {dispatcher.shipReadiness(ship.symbol)}")

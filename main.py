import logging
import os
import sys

from dotenv import load_dotenv

from api.client import ApiClient
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
    logging.error("Error: AGENT_TOKEN not found in environment.")
    logging.error("Please set AGENT_TOKEN in your .env file or environment.")
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

# Initialize the minHeap with the ships, using the shipReadiness as the priority
for ship in dataWarehouse.ships_by_symbol.values():
    event_queue.push(ship.symbol, dispatcher.shipReadiness(ship.symbol))
    logging.info(
        f"Ship added to event queue: {ship.symbol} - {ship.registration.role} - Readiness: {dispatcher.shipReadiness(ship.symbol)}"
    )

# log the intial size of the queue
logging.info(f"Initial size of event queue: {event_queue.size()}")

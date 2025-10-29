import logging
import os
import sys
import time

from dotenv import load_dotenv

from api.client import ApiClient
from data.enums import ShipAction
from data.warehouse import Warehouse
from flow.queue import MinHeap
from logic.navigation import Navigation
from logic.navigation_algorithms import NavigationAlgorithms
from logic.scanner import Scanner
from logic.utility import get_utc_timestamp
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

while True:
    next_priority = event_queue.peek_next_priority()
    if next_priority is None:
        logging.info("No ships in event queue")
        break
    if next_priority > get_utc_timestamp():
        time_to_sleep = next_priority - get_utc_timestamp()
        logging.info(f"Sleeping for {time_to_sleep} seconds")
        time.sleep(time_to_sleep)
        continue
    event = event_queue.extract_min()
    if event is None:
        logging.info("No ships in event queue")
        break
    ship = dataWarehouse.ships_by_symbol.get(event)
    if ship is None:
        logging.error(f"Ship no longer exists: {event}")
        continue
    # Decide exactly one action to take, then execute it.
    action = dispatcher.decide_next_action(ship.symbol)
    logging.info(
        f"Ship: {ship.symbol} - Fuel: {ship.fuel.current}/{ship.fuel.capacity} - Cargo: {ship.cargo.units}/{ship.cargo.capacity} - Action: {action}"
    )
    if action == ShipAction.REFUEL:
        navigator.refuel(ship.symbol)
        logging.info(
            f"Refueled ship: {ship.symbol} - Fuel: {ship.fuel.current}/{ship.fuel.capacity} - Credits: {credits}"
        )
    elif action == ShipAction.NAVIGATE_TO_MINE:
        closest_mineable_waypoint = navigatorAlgorithms.find_closest_mineable_waypoint(ship.symbol)
        logging.info(f"Closest mineable waypoint: {closest_mineable_waypoint}")
        if closest_mineable_waypoint:
            navigator.navigate_in_system(ship.symbol, closest_mineable_waypoint)
            logging.info(f"Navigating to {closest_mineable_waypoint}")
    # Always re-queue after one action (or no-op)
    # add ship back to the event queue
    event_queue.push(ship.symbol, dispatcher.shipReadiness(ship.symbol))
    logging.info(
        f"Ship added back to event queue: {ship.symbol} - {ship.registration.role} - Readiness: {dispatcher.shipReadiness(ship.symbol)}"
    )

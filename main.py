from dotenv import load_dotenv
import os
import sys
import configparser
import time
import logging

from api.client import ApiClient
from data.warehouse import Warehouse
from data.enums import WaypointTraitType, ShipRole
from logic.scanner import Scanner
from logic.mine import Mine
from logic.navigation import Navigation
from policy.dispatcher import Dispatcher
# load environment variables
load_dotenv()

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Validate required environment variables
agent_token = os.getenv("AGENT_TOKEN")
if not agent_token:
    print("Error: AGENT_TOKEN not found in environment.", file=sys.stderr)
    print("Please set AGENT_TOKEN in your .env file or environment.", file=sys.stderr)
    sys.exit(1)

logging.info("Systems initializing")

#create an api instance to hold the key for all api calls
client = ApiClient(agent_token)
dataWarehouse = Warehouse()  
scanner = Scanner(client, dataWarehouse)
navigator = Navigation(client, dataWarehouse)

logging.info("All systems operational.")
credits = scanner.get_credits()
logging.info(f"Credits: {credits}")

dispatcher = Dispatcher(dataWarehouse, scanner)
dispatcher.fill_ship_queue()
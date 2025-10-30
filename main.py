import logging
import os
import sys

from dotenv import load_dotenv

from app.bootstrap import build_app
from flow.scheduler import run_scheduler

# load environment variables
load_dotenv()

# logging.basicConfig(level=logging.DEBUG, format="%(asctime)s - %(levelname)s - %(message)s")
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

# Validate required environment variables
agent_token = os.getenv("AGENT_TOKEN")
if not agent_token:
    logging.error("Error: AGENT_TOKEN not found in environment.")
    logging.error("Please set AGENT_TOKEN in your .env file or environment.")
    sys.exit(1)

ctx = build_app(agent_token)
run_scheduler(ctx)

from dotenv import load_dotenv
import os

from api.agent import agent
from data.warehouse import warehouse
from api.systems import systems
from api.waypoints import list_waypoints
# load environment variables
load_dotenv()

# get the API key from the environment variables
agent_key = os.getenv("AGENT_TOKEN")
agent = agent(agent_key)
data = agent.get()['data']

dataWarehouse = warehouse()

for key, value in data.items():
    setattr(dataWarehouse, key, value)
    

print(dataWarehouse)

systems_api = systems(agent_key)
systems_payload = systems_api.get()['data']
loaded_systems = dataWarehouse.upsert_systems(systems_payload)
print(f"Populated {len(loaded_systems)} systems")

# Hydrate waypoints for HQ system to improve waypoint knowledge
if dataWarehouse.headquarters and "-" in dataWarehouse.headquarters:
    hq_system = dataWarehouse.headquarters.split("-")[0] + "-" + dataWarehouse.headquarters.split("-")[1]
    details = list_waypoints(hq_system, agent_key, page=1, limit=20)
    if details:
        dataWarehouse.upsert_waypoints_detail(details)
        print(f"Populated {len(details)} waypoints for system {hq_system}")
    
    

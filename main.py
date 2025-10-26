from dotenv import load_dotenv
import os

from api.agent import agent
from data.warehouse import warehouse
from api.systems import systems
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

systems = systems(agent_key)
systemData = systems.get()['data'][0]

for key, value in systemData.items():
    if key != 'waypoints':
        print(key, value)
    elif key == 'waypoints':
        print(f"{len(value)} waypoints")
    
    

from api.handle_requests import get_json

class systems():
    def __init__(self, agent_key: str):
        self.agent_key = agent_key

    def get(self):
        return get_json("systems", self.agent_key)
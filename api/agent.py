from api.handle_requests import get_json

class agent():
    def __init__(self, agent_key: str):
        self.agent_key = agent_key

    def get(self):
        return get_json("my/agent", self.agent_key)
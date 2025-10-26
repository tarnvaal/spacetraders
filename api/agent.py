from api.handle_requests import spacetraders_get

class agent():
    def __init__(self, agent_key: str):
        self.url = "https://api.spacetraders.io/v2/my/agent"
        self.headers = {
            "Authorization": f"Bearer {agent_key}"
        }

    def get(self):
        response = spacetraders_get(self.url, headers=self.headers)
        return response.json()
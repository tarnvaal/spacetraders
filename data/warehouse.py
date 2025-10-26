from dataclasses import dataclass
from typing import Any, Dict

class warehouse():
    accountId: str = ""
    symbol: str = ""
    headquarters: str = ""
    credits: int = 0
    startingFaction: str = ""
    shipCount: int = 0
    
    
    def __str__(self):
        output = ""
        output += f"Account ID: {self.accountId}\n"
        output += f"Symbol: {self.symbol}\n"
        output += f"Headquarters: {self.headquarters}\n"
        output += f"Credits: {self.credits}\n"
        output += f"Starting Faction: {self.startingFaction}\n"
        output += f"Ship Count: {self.shipCount}\n"
        return output
from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class SystemFaction:
    symbol: str


@dataclass
class SystemWaypointRef:
    symbol: str
    type: str
    x: int
    y: int
    orbitals: List[str] = field(default_factory=list)
    orbits: Optional[str] = None


@dataclass
class System:
    symbol: str
    sectorSymbol: str
    type: str
    x: int
    y: int
    waypoints: List[SystemWaypointRef]
    factions: List[SystemFaction]

    @staticmethod
    def from_dict(d: dict) -> "System":
        return System(
            symbol=d["symbol"],
            sectorSymbol=d["sectorSymbol"],
            type=d["type"],
            x=d["x"],
            y=d["y"],
            waypoints=[
                SystemWaypointRef(
                    symbol=w.get("symbol"),
                    type=w.get("type"),
                    x=w.get("x"),
                    y=w.get("y"),
                    orbitals=[o.get("symbol") for o in w.get("orbitals", []) if isinstance(o, dict) and "symbol" in o],
                    orbits=w.get("orbits"),
                )
                for w in d.get("waypoints", [])
                if w and all(k in w for k in ("symbol", "type", "x", "y"))
            ],
            factions=[
                SystemFaction(symbol=f.get("symbol"))
                for f in d.get("factions", [])
                if f and "symbol" in f
            ],
        )



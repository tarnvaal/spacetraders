from dataclasses import dataclass, field
from typing import List, Optional

@dataclass
class WaypointTrait:
    symbol: str
    name: Optional[str] = None
    description: Optional[str] = None


@dataclass
class WaypointFactionRef:
    symbol: str


@dataclass
class WaypointChart:
    submittedBy: Optional[str] = None
    submittedOn: Optional[str] = None 


@dataclass
class Waypoints:
    symbol: str
    systemSymbol: str
    type: str
    x: int
    y: int
    orbitals: List[str] = field(default_factory=list)
    orbits: Optional[str] = None
    faction: Optional[WaypointFactionRef] = None
    traits: List[WaypointTrait] = field(default_factory=list)
    chart: Optional[WaypointChart] = None
    isUnderConstruction: Optional[bool] = None

    @staticmethod
    def from_detail_dict(d: dict) -> "Waypoints":
        return Waypoints(
            symbol=d["symbol"],
            systemSymbol=d.get("systemSymbol", ""),
            type=d["type"],
            x=d["x"],
            y=d["y"],
            orbitals=[o.get("symbol") for o in d.get("orbitals", []) if isinstance(o, dict) and "symbol" in o],
            orbits=d.get("orbits"),
            faction=WaypointFactionRef(symbol=d["faction"]["symbol"]) if isinstance(d.get("faction"), dict) and "symbol" in d["faction"] else None,
            traits=[WaypointTrait(symbol=t.get("symbol"), name=t.get("name"), description=t.get("description")) for t in d.get("traits", []) if isinstance(t, dict) and "symbol" in t],
            chart=WaypointChart(submittedBy=d["chart"].get("submittedBy"), submittedOn=d["chart"].get("submittedOn")) if isinstance(d.get("chart"), dict) else None,
            isUnderConstruction=d.get("isUnderConstruction"),
        )



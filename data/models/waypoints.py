from dataclasses import dataclass, field


@dataclass
class WaypointTrait:
    symbol: str
    name: str | None = None
    description: str | None = None


@dataclass
class WaypointFactionRef:
    symbol: str


@dataclass
class WaypointChart:
    submittedBy: str | None = None
    submittedOn: str | None = None


@dataclass
class Waypoints:
    symbol: str
    systemSymbol: str
    type: str
    x: int
    y: int
    orbitals: list[str] = field(default_factory=list)
    orbits: str | None = None
    faction: WaypointFactionRef | None = None
    traits: list[WaypointTrait] = field(default_factory=list)
    chart: WaypointChart | None = None
    isUnderConstruction: bool | None = None

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
            faction=(
                WaypointFactionRef(symbol=d["faction"]["symbol"])
                if isinstance(d.get("faction"), dict) and "symbol" in d["faction"]
                else None
            ),
            traits=[
                WaypointTrait(symbol=t.get("symbol"), name=t.get("name"), description=t.get("description"))
                for t in d.get("traits", [])
                if isinstance(t, dict) and "symbol" in t
            ],
            chart=(
                WaypointChart(submittedBy=d["chart"].get("submittedBy"), submittedOn=d["chart"].get("submittedOn"))
                if isinstance(d.get("chart"), dict)
                else None
            ),
            isUnderConstruction=d.get("isUnderConstruction"),
        )

from dataclasses import dataclass, field


@dataclass
class SystemFaction:
    symbol: str


@dataclass
class SystemWaypointRef:
    symbol: str
    type: str
    x: int
    y: int
    orbitals: list[str] = field(default_factory=list)
    orbits: str | None = None


@dataclass
class System:
    symbol: str
    sectorSymbol: str
    type: str
    x: int
    y: int
    waypoints: list[SystemWaypointRef]
    factions: list[SystemFaction]

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
            factions=[SystemFaction(symbol=f.get("symbol")) for f in d.get("factions", []) if f and "symbol" in f],
        )

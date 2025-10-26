from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from data.models.system import System, SystemWaypointRef
from data.models.waypoint import Waypoint

@dataclass
class Warehouse():
    accountId: str = ""
    symbol: str = ""
    headquarters: str = ""
    credits: int = 0
    startingFaction: str = ""
    shipCount: int = 0
    sectorsKnown: Optional[Dict[str, Any]] = None

    # Indexed storage for SpaceTraders systems (per-instance)
    systems_by_symbol: Dict[str, System] = field(default_factory=dict)
    waypoints_by_symbol: Dict[str, SystemWaypointRef] = field(default_factory=dict)
    full_waypoints_by_symbol: Dict[str, Waypoint] = field(default_factory=dict)

    def __post_init__(self):
        if self.sectorsKnown is None:
            self.sectorsKnown = {
                'sectorSymbol': "",
                'type': "",
                'x': 0,
                'y': 0,
                'waypoints':  0,
                'factions': [],
                'constellation': "",
                'name': "",
            }

    def load_agent_data(self, data: Dict[str, Any]) -> None:
        known_keys = {
            'accountId', 'symbol', 'headquarters',
            'credits', 'startingFaction', 'shipCount'
        }
        for key in known_keys:
            if key in data:
                setattr(self, key, data[key])

    def upsert_system(self, payload: Dict[str, Any]) -> System:
        sys = System.from_dict(payload)
        self.systems_by_symbol[sys.symbol] = sys
        for wp in sys.waypoints:
            self.waypoints_by_symbol[wp.symbol] = wp
        return sys

    def upsert_systems(self, payloads: List[Dict[str, Any]]) -> List[System]:
        return [self.upsert_system(p) for p in payloads]

    def get_system(self, symbol: str) -> Optional[System]:
        return self.systems_by_symbol.get(symbol)

    def get_systems_in_sector(self, sector_symbol: str) -> List[System]:
        return [s for s in self.systems_by_symbol.values() if s.sectorSymbol == sector_symbol]

    def systems_count(self) -> int:
        return len(self.systems_by_symbol)

    # Waypoint detail upserts/lookups
    def upsert_waypoint_detail(self, payload: Dict[str, Any]) -> Waypoint:
        w = Waypoint.from_detail_dict(payload)
        self.full_waypoints_by_symbol[w.symbol] = w
        # Refresh ref index with any new info
        ref = self.waypoints_by_symbol.get(w.symbol)
        if ref is None:
            # Create a minimal ref if it didn't exist from systems payload
            ref = SystemWaypointRef(
                symbol=w.symbol,
                type=w.type,
                x=w.x,
                y=w.y,
                orbitals=list(w.orbitals),
                orbits=w.orbits,
            )
            self.waypoints_by_symbol[w.symbol] = ref
        else:
            # Update known fields
            ref.type = w.type
            ref.x = w.x
            ref.y = w.y
            ref.orbitals = list(w.orbitals)
            ref.orbits = w.orbits
        return w

    def upsert_waypoints_detail(self, payloads: List[Dict[str, Any]]) -> List[Waypoint]:
        return [self.upsert_waypoint_detail(p) for p in payloads]

    def get_waypoint_ref(self, symbol: str) -> Optional[SystemWaypointRef]:
        return self.waypoints_by_symbol.get(symbol)

    def get_waypoint(self, symbol: str) -> Optional[Waypoint]:
        return self.full_waypoints_by_symbol.get(symbol)

    def get_waypoints_in_system(self, system_symbol: str) -> List[SystemWaypointRef]:
        sys = self.systems_by_symbol.get(system_symbol)
        return list(sys.waypoints) if sys else []

    def get_children(self, symbol: str) -> List[SystemWaypointRef]:
        wp = self.waypoints_by_symbol.get(symbol)
        if not wp:
            return []
        return [self.waypoints_by_symbol[s] for s in wp.orbitals if s in self.waypoints_by_symbol]

    def get_parent(self, symbol: str) -> Optional[SystemWaypointRef]:
        wp = self.waypoints_by_symbol.get(symbol)
        if not wp or not wp.orbits:
            return None
        return self.waypoints_by_symbol.get(wp.orbits)

    
    
    def __str__(self):
        output = ""
        output += f"Account ID: {self.accountId}\n"
        output += f"Symbol: {self.symbol}\n"
        output += f"Headquarters: {self.headquarters}\n"
        output += f"Credits: {self.credits}\n"
        output += f"Starting Faction: {self.startingFaction}\n"
        output += f"Ship Count: {self.shipCount}\n"
        return output
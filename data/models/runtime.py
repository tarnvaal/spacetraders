from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class ShipState(Enum):
    IDLE = "IDLE"
    NAVIGATING = "NAVIGATING"
    MINING = "MINING"


@dataclass
class ShipRuntime:
    state: ShipState = ShipState.IDLE
    next_wakeup_ts: str | None = None
    context: dict[str, Any] = field(default_factory=dict)

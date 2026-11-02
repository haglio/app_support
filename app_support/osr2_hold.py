from __future__ import annotations

from pathlib import Path
from types import MappingProxyType

from .file_channel import append_command
from .state_files import BROKER_CMD

__all__ = [
    "HOLD_DELAY_S", "HOLD_MOVE_MS", "PARK", "RESUME", "RETRACT", "ask_the_broker",
    "hold_tcode",
]

PARK = "PARK"
RETRACT = "RETRACT"
RESUME = "RESUME"

HOLD_DELAY_S = 1.0
HOLD_MOVE_MS = MappingProxyType({PARK: 1000, RETRACT: 500})
_HOLD_POSITION = MappingProxyType({PARK: 0, RETRACT: 9999})


def hold_tcode(hold: str) -> str:
    return f"L0{_HOLD_POSITION[hold]:04d}I{HOLD_MOVE_MS[hold]}"


def ask_the_broker(broker_state_dir: Path, verb: str) -> bool:
    return append_command(broker_state_dir / BROKER_CMD, verb)

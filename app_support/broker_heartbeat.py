from __future__ import annotations

from pathlib import Path

from . import state_files
from .file_channel import stamp_age

FRESH_S = 3.0


def is_fresh(state_dir: Path, *, now: float | None = None) -> bool:
    age = stamp_age(Path(state_dir) / state_files.BROKER_HEARTBEAT, now)
    return age is not None and age <= FRESH_S

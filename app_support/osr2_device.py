"""Whether the OSR2 is switched on, read the one way every app reads it."""
from __future__ import annotations

from pathlib import Path

from .file_channel import stamp_age

__all__ = ["SILENT_ONCE_OFF_S", "switched_on"]

# A powered OSR2 reports its temperature on its own about every 15 s, and that
# is the only sign it has power: the USB adapter takes whatever is sent to it,
# switched on or not.
SILENT_ONCE_OFF_S = 20.0


def switched_on(rx_stamp: Path, *, now: float | None = None) -> bool:
    age = stamp_age(rx_stamp, now)
    return age is not None and age < SILENT_ONCE_OFF_S

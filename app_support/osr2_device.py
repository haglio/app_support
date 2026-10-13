"""Whether the OSR2 is switched on, and in its own auto mode, read the one way
every app reads it."""
from __future__ import annotations

from enum import StrEnum
from pathlib import Path

from .file_channel import read_flag, stamp_age
from .state_files import BROKER_MODE, OSR2_SERIAL_ANSWER, OSR2_SERIAL_RX

__all__ = [
    "ANSWERING_TRUSTED_S", "ANSWERS_ONCE_OFF_S", "SILENT_ONCE_OFF_S",
    "Osr2Mode", "mode", "switched_on",
]

# The USB adapter takes whatever is sent to it, switched on or not, so only the
# OSR2's own words say it has power.  While it answers the broker's question, a
# second without an answer means it is off; one not answering is judged by the
# temperature it reports on its own about every 15 s.
SILENT_ONCE_OFF_S = 20.0
ANSWERS_ONCE_OFF_S = 1.0
ANSWERING_TRUSTED_S = 30.0


class Osr2Mode(StrEnum):
    OFF = "off"
    AUTO = "auto"
    CONTROLLED = "controlled"


def switched_on(state_dir: Path, *, now: float | None = None) -> bool:
    answered = stamp_age(state_dir / OSR2_SERIAL_ANSWER, now)
    if answered is not None and answered < ANSWERING_TRUSTED_S:
        return answered < ANSWERS_ONCE_OFF_S
    age = stamp_age(state_dir / OSR2_SERIAL_RX, now)
    return age is not None and age < SILENT_ONCE_OFF_S


def mode(state_dir: Path, *, now: float | None = None) -> Osr2Mode:
    if not switched_on(state_dir, now=now):
        return Osr2Mode.OFF
    if read_flag(state_dir / BROKER_MODE, default=False):
        return Osr2Mode.AUTO
    return Osr2Mode.CONTROLLED

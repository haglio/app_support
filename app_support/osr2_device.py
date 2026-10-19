"""Whether the OSR2 is switched on, in its own auto mode, or out of the
computer's hearing, read the one way every app reads it."""
from __future__ import annotations

from enum import StrEnum
from pathlib import Path

from .file_channel import read_flag, stamp_age
from .state_files import (
    BROKER_MODE,
    OSR2_NOT_ANSWERING,
    OSR2_NOT_FOUND,
    OSR2_SERIAL_ANSWER,
    OSR2_SERIAL_RX,
)

__all__ = [
    "ANSWERING_TRUSTED_S", "ANSWERS_ONCE_OFF_S", "SILENT_ONCE_OFF_S", "TROUBLE_RENEWED_WITHIN_S",
    "Osr2Mode", "Osr2Trouble", "mode", "switched_on", "trouble",
]

# The USB adapter takes whatever is sent to it, switched on or not, so only the
# OSR2's own words say it has power.  While it answers the broker's question, a
# second without an answer means it is off; one not answering is judged by the
# temperature it reports on its own about every 15 s.
SILENT_ONCE_OFF_S = 20.0
ANSWERS_ONCE_OFF_S = 1.0
ANSWERING_TRUSTED_S = 30.0
TROUBLE_RENEWED_WITHIN_S = 3.0


class Osr2Mode(StrEnum):
    OFF = "off"
    AUTO = "auto"
    CONTROLLED = "controlled"


class Osr2Trouble(StrEnum):
    NOT_FOUND = "not_found"
    NOT_ANSWERING = "not_answering"


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


_TROUBLE_STAMPS = {Osr2Trouble.NOT_FOUND: OSR2_NOT_FOUND, Osr2Trouble.NOT_ANSWERING: OSR2_NOT_ANSWERING}


def trouble(state_dir: Path, *, now: float | None = None) -> Osr2Trouble | None:
    if switched_on(state_dir, now=now):
        return None
    for kind, name in _TROUBLE_STAMPS.items():
        age = stamp_age(state_dir / name, now)
        if age is not None and age < TROUBLE_RENEWED_WITHIN_S:
            return kind
    return None

"""The four files an Origenerator opened on its own and a Fun Time session hand
that Origenerator over through, spelled, written and read once for both apps.

The Origenerator offers itself (OFFER) and says the shape of the slideshow it
shows (SHOWING); a session hands the copy it finds its launch (TAKEOVER), taken
once, rather than starting a second, and claims the OSR2 for as long as it runs
(SESSION).  A pid names a process only beside the time it started, since
Windows gives a freed pid out again within seconds.  Copies of the two apps can
run different releases of this module, so what one release writes, every later
one reads.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import NamedTuple

from app_support.siblings import primary_checkout_of
from app_support.win32 import process_started

OFFER = "fun_time_offer.txt"
SHOWING = "fun_time_showing.txt"
TAKEOVER = "fun_time_takeover.json"
SESSION = "fun_time_session.txt"

STILL_STARTING = "starting"
SHAPES = ("portrait", "landscape", "both")

_A_PROCESS = r"(\d+) (\d+)"
_AN_OFFER = re.compile(rf"{_A_PROCESS}(?: ({STILL_STARTING}))?")
_A_MARK = re.compile(rf"{_A_PROCESS}(?: ({'|'.join(SHAPES)}))?")
_A_CLAIM = re.compile(_A_PROCESS)
_PID, _ARGS = "pid", "args"


class Process(NamedTuple):
    pid: int
    created_at: int

    def __str__(self) -> str:
        return f"{self.pid} {self.created_at}"

    def is_running(self) -> bool:
        return process_started(self.pid) == self.created_at


class Offer(NamedTuple):
    process: Process
    starting: bool


class Takeover(NamedTuple):
    pid: int
    args: list[str]


def this_process() -> Process:
    created_at = process_started(os.getpid())
    if created_at is None:
        raise OSError("Windows would not say when this process started")
    return Process(os.getpid(), created_at)


def meeting_places(checkout: Path) -> tuple[Path, ...]:
    return tuple(dict.fromkeys(place / "state" for place in (checkout, primary_checkout_of(checkout))))


def offer_of(process: Process, *, starting: bool = False) -> str:
    return f"{process} {STILL_STARTING}" if starting else str(process)


def offer_this_process(*places: Path, starting: bool = False) -> None:
    offer = offer_of(this_process(), starting=starting)
    for place in places:
        place.mkdir(parents=True, exist_ok=True)
        (place / OFFER).write_text(offer, encoding="utf-8")


def the_offer_in(place: Path) -> Offer | None:
    offer = _read(place / OFFER, _AN_OFFER)
    if offer is None:
        return None
    process = _process_of(offer)
    return Offer(process, starting=offer[3] is not None) if process.is_running() else None


def slideshow_mark_of(process: Process, shape: str) -> str:
    return f"{process} {shape}"


def the_shape_shown_in(place: Path, *, by: Process) -> str | None:
    mark = _read(place / SHOWING, _A_MARK)
    if mark is None or _process_of(mark) != by:
        return None
    return mark[3] or "both"


def withdraw_the_offer(*places: Path) -> None:
    for place in places:
        (place / OFFER).unlink(missing_ok=True)
        (place / SHOWING).unlink(missing_ok=True)


def hand_over(place: Path, *, pid: int, args: list[str]) -> None:
    takeover = place / TAKEOVER
    staged = takeover.with_name(f"{TAKEOVER}.tmp")
    staged.write_text(json.dumps({_PID: pid, _ARGS: args}), encoding="utf-8")
    os.replace(staged, takeover)


def a_takeover_waits_in(place: Path) -> bool:
    return (place / TAKEOVER).exists()


def take_the_takeover(place: Path) -> Takeover | None:
    takeover = place / TAKEOVER
    if not takeover.exists():
        return None
    try:
        asked = json.loads(takeover.read_text(encoding="utf-8"))
        return Takeover(asked[_PID], asked[_ARGS])
    except (ValueError, TypeError, KeyError) as not_one:
        raise ValueError(f"{takeover} holds no takeover: {not_one!r}") from not_one
    finally:
        takeover.unlink(missing_ok=True)


def claim_the_osr2(*places: Path) -> None:
    claim = str(this_process())
    for place in places:
        place.mkdir(parents=True, exist_ok=True)
        (place / SESSION).write_text(claim, encoding="utf-8")


def a_session_claims_the_osr2(place: Path) -> bool:
    claim = _read(place / SESSION, _A_CLAIM)
    return claim is not None and _process_of(claim).is_running()


def _read(path: Path, line: re.Pattern) -> re.Match | None:
    try:
        return line.fullmatch(path.read_text(encoding="utf-8").strip())
    except OSError:
        return None


def _process_of(line: re.Match) -> Process:
    return Process(int(line[1]), int(line[2]))

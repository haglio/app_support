"""Fun Time's integration runs, written down by each run and read by Line."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, fields
from datetime import UTC, datetime, timedelta
from pathlib import Path

from app_support.file_channel import read_whole, write_whole
from app_support.win32 import process_started

_TIMES = ("joined", "got_the_machine", "ended", "seen")


def runs_dir(fun_time: Path) -> Path:
    return fun_time / "state" / "integration_runs"


@dataclass(frozen=True)
class RunRecord:
    checkout: str
    branch: str
    what: list[str]
    short: bool
    pid: int
    joined: datetime
    session: str = ""
    process_started: int | None = None
    got_the_machine: datetime | None = None
    ended: datetime | None = None
    exit_code: int | None = None
    seen: datetime | None = None

    def to_json(self) -> str:
        written = {key: value for key, value in asdict(self).items() if value is not None}
        for key in _TIMES:
            if key in written:
                written[key] = written[key].isoformat(timespec="seconds")
        return json.dumps(written, indent=1)

    @classmethod
    def from_json(cls, text: str) -> RunRecord:
        read = {key: value for key, value in json.loads(text).items() if key in _FIELDS}
        for key in _TIMES:
            if read.get(key):
                read[key] = datetime.fromisoformat(read[key])
        return cls(**read)


_FIELDS = {each.name for each in fields(RunRecord)}


def write_run(folder: Path, run: RunRecord) -> Path:
    path = folder / f"{run.joined:%Y%m%d-%H%M%S}-{run.pid}.json"
    write_whole(path, run.to_json())
    return path


_FILETIME_ZERO = datetime(1601, 1, 1, tzinfo=UTC)
_JOINED_TO_THE_SECOND = timedelta(seconds=1)


def still_going(run: RunRecord) -> bool:
    if run.ended is not None:
        return False
    started = process_started(run.pid)
    if started is None:
        return False
    if run.process_started is None:
        return _FILETIME_ZERO + timedelta(microseconds=started // 10) < run.joined + _JOINED_TO_THE_SECOND
    return started == run.process_started


def read_run(path: Path) -> RunRecord:
    return RunRecord.from_json(read_whole(path))


def read_runs(folder: Path) -> list[RunRecord]:
    runs = []
    for path in sorted(folder.glob("*.json")):
        try:
            runs.append(read_run(path))
        except (OSError, ValueError, TypeError):
            continue
    return runs

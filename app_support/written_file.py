from __future__ import annotations

import os
import time
from collections.abc import Callable
from pathlib import Path

_Written = tuple[int, int, int]
_NEVER_READ = (-1, -1, -1)

# Windows stamps a file from a clock that can stand still for 15.6 ms, so two writes in place, of
# one length, inside one tick of it leave nothing os.stat can tell apart. A file stamped this
# lately is taken as written again however it reads.
STAMPED_TOO_LATELY_TO_TELL_NS = 200_000_000


def stamped_too_lately_to_tell(mtime_ns: int, now_ns: int) -> bool:
    return abs(now_ns - mtime_ns) <= STAMPED_TOO_LATELY_TO_TELL_NS


class WrittenFile:
    # The family's channel files are replaced, so each write is a new file with an identity of
    # its own, which tells two writes apart though Windows stamped both with one time.

    def __init__(self, path: Path, *, now_ns: Callable[[], int] = time.time_ns) -> None:
        self._path = Path(path)
        self._now_ns = now_ns
        self._read_as: _Written | None = _NEVER_READ
        self._found: _Written | None = None

    @property
    def path(self) -> Path:
        return self._path

    def may_have_been_written(self) -> bool:
        try:
            found = os.stat(self._path)
        except OSError:
            self._found = None
        else:
            self._found = (found.st_ino, found.st_size, found.st_mtime_ns)
        return self._found != self._read_as

    @property
    def holds_something(self) -> bool:
        return self._found is not None and self._found[1] > 0

    def was_read(self) -> None:
        lately = self._found is not None and stamped_too_lately_to_tell(
            self._found[2], self._now_ns())
        self._read_as = _NEVER_READ if lately else self._found


class ReadWhenChanged[T]:
    def __init__(self, path: Path, read: Callable[[Path], T], *,
                 now_ns: Callable[[], int] = time.time_ns) -> None:
        self._file = WrittenFile(path, now_ns=now_ns)
        self._read = read
        self._value: T | None = None

    def latest(self) -> T | None:
        if not self._file.may_have_been_written():
            return self._value
        try:
            value = self._read(self._file.path)
        except OSError:
            return self._value
        self._file.was_read()
        self._value = value
        return value

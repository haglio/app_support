from __future__ import annotations

import os
import threading
import time
from collections import OrderedDict
from collections.abc import Callable
from contextlib import AbstractContextManager, nullcontext
from dataclasses import dataclass
from pathlib import Path

_Written = tuple[int, int, int]
Dating = Callable[[Path], os.stat_result]
_NEVER_READ = (-1, -1, -1)

# Windows stamps a file from a clock that can stand still for 15.6 ms, so two writes in place, of
# one length, inside one tick of it leave nothing os.stat can tell apart. A file stamped this
# lately is taken as written again however it reads.
STAMPED_TOO_LATELY_TO_TELL_NS = 200_000_000


def stamped_too_lately_to_tell(mtime_ns: int, now_ns: int,
                               too_lately_ns: int = STAMPED_TOO_LATELY_TO_TELL_NS) -> bool:
    return abs(now_ns - mtime_ns) <= too_lately_ns


class WrittenFile:
    # The family's channel files are replaced, so each write is a new file with an identity of
    # its own, which tells two writes apart though Windows stamped both with one time.

    def __init__(self, path: Path, *, now_ns: Callable[[], int] = time.time_ns,
                 stat: Dating = os.stat,
                 too_lately_ns: int = STAMPED_TOO_LATELY_TO_TELL_NS) -> None:
        self._path = Path(path)
        self._now_ns = now_ns
        self._stat = stat
        self._too_lately_ns = too_lately_ns
        self._read_as: _Written | None = _NEVER_READ
        self._found: _Written | None = None

    @property
    def path(self) -> Path:
        return self._path

    def may_have_been_written(self) -> bool:
        try:
            found = self._stat(self._path)
        except OSError:
            self._found = None
        else:
            self._found = (found.st_ino, found.st_size, found.st_mtime_ns)
        return self._found != self._read_as

    @property
    def holds_something(self) -> bool:
        return self._found is not None and self._found[1] > 0

    def was_read(self) -> None:
        self.was_read_as(self._found)

    @property
    def found(self) -> _Written | None:
        return self._found

    def was_read_as(self, found: _Written | None) -> None:
        lately = found is not None and stamped_too_lately_to_tell(
            found[2], self._now_ns(), self._too_lately_ns)
        self._read_as = _NEVER_READ if lately else found


@dataclass(frozen=True)
class Look[T]:
    fresh: bool
    holds_something: bool
    value: T | None
    keep: Callable[[T], T]


class ReadWhenChanged[T]:
    def __init__(self, path: Path, read: Callable[[Path], T], *,
                 now_ns: Callable[[], int] = time.time_ns, stat: Dating = os.stat,
                 too_lately_ns: int = STAMPED_TOO_LATELY_TO_TELL_NS,
                 guard: AbstractContextManager | None = None) -> None:
        self._file = WrittenFile(path, now_ns=now_ns, stat=stat, too_lately_ns=too_lately_ns)
        self._read = read
        self._value: T | None = None
        self._guard = guard or nullcontext()

    def look(self) -> Look[T]:
        with self._guard:
            fresh = not self._file.may_have_been_written()
            found, holds_something, kept = self._file.found, self._file.holds_something, self._value

        def keep(value: T) -> T:
            with self._guard:
                self._file.was_read_as(found)
                self._value = value
            return value
        return Look(fresh, holds_something, kept, keep)

    def latest(self) -> T | None:
        looked = self.look()
        if looked.fresh:
            return looked.value
        try:
            value = self._read(self._file.path)
        except OSError:
            return looked.value
        return looked.keep(value)


class ReadEachWhenChanged[K, T]:
    def __init__(self, read: Callable[[K], T] | None = None, *, most: int,
                 path_of: Callable[[K], Path] = Path,
                 now_ns: Callable[[], int] = time.time_ns, stat: Dating = os.stat,
                 too_lately_ns: int = STAMPED_TOO_LATELY_TO_TELL_NS) -> None:
        self._read = read
        self._most = most
        self._path_of = path_of
        self._now_ns = now_ns
        self._stat = stat
        self._too_lately_ns = too_lately_ns
        self._readers: OrderedDict[K, ReadWhenChanged[T]] = OrderedDict()
        self._guard = threading.Lock()

    def __len__(self) -> int:
        return len(self._readers)

    def _reader(self, key: K) -> ReadWhenChanged[T]:
        with self._guard:
            reader = self._readers.get(key)
        if reader is None:
            reader = ReadWhenChanged(
                self._path_of(key), lambda _path: self._read(key),
                now_ns=self._now_ns, stat=self._stat, too_lately_ns=self._too_lately_ns,
                guard=self._guard)
        with self._guard:
            reader = self._readers.setdefault(key, reader)
            self._readers.move_to_end(key)
            if len(self._readers) > self._most:
                self._readers.popitem(last=False)
        return reader

    def look(self, key: K) -> Look[T]:
        return self._reader(key).look()

    def latest(self, key: K) -> T | None:
        return self._reader(key).latest()

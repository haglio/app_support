from __future__ import annotations

import logging
import threading
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass

from app_support.pcloud.api import CloudFile, FileLink, PCloud, PCloudRefused, read_span
from app_support.pcloud.chunks import ChunkStore

logger = logging.getLogger(__name__)

CHUNK_BYTES = 4 * 1024 * 1024
LINK_RENEWED_THIS_LONG_BEFORE_IT_EXPIRES_S = 60
A_LISTING_IS_ASKED_AGAIN_AFTER_S = 600
A_LISTING_LACKING_A_FILE_IS_ASKED_AGAIN_AFTER_S = 2
_PCLOUDS_NO_SUCH_FOLDER = 2005
ANOTHER_WRITERS_CHUNK_IS_LOOKED_FOR_EVERY_S = 0.02
A_DOWNLOADS_ATTEMPTS = 3


class WrongLength(OSError):
    pass


class NotInPCloud(LookupError):
    pass


@dataclass(frozen=True)
class Entry:
    path: str
    fileid: int
    size: int
    key: str


class Fetcher:
    def __init__(self, pcloud: PCloud, store: ChunkStore, *, chunk_bytes: int = CHUNK_BYTES,
                 read: Callable[[str, int, int], bytes] = read_span, now: Callable[[], float] = time.time,
                 sleep: Callable[[float], None] = time.sleep) -> None:
        self._pcloud, self._store, self._chunk_bytes, self._read = pcloud, store, chunk_bytes, read
        self._now, self._sleep = now, sleep
        self._links: dict[int, FileLink] = {}
        self._listings: dict[str, tuple[dict[str, CloudFile], float]] = {}
        self._plans: dict[str, deque[tuple[Entry, int]]] = {}
        self._planned_files: dict[str, frozenset[str]] = {}
        self._being_read: set[str] = set()
        self._lock = threading.Lock()
        self._work_arrived = threading.Condition(self._lock)
        self._closed = False

    def entry(self, path: str) -> Entry:
        folder, _, name = path.rpartition("/")
        found = self._listing(folder or "/", A_LISTING_IS_ASKED_AGAIN_AFTER_S).get(name) \
            or self._listing(folder or "/", A_LISTING_LACKING_A_FILE_IS_ASKED_AGAIN_AFTER_S).get(name)
        if found is None:
            raise NotInPCloud(path)
        return Entry(path=path, fileid=found.fileid, size=found.size, key=f"{found.fileid}-{found.hash}")

    def _listing(self, folder: str, kept_for_s: float) -> dict[str, CloudFile]:
        with self._lock:
            known = self._listings.get(folder)
        if known is not None and self._now() - known[1] < kept_for_s:
            return known[0]
        try:
            listed = self._pcloud.list_folder(folder)
        except PCloudRefused as refused:
            if refused.code != _PCLOUDS_NO_SUCH_FOLDER:
                raise
            listed = {}
        with self._lock:
            self._listings[folder] = (listed, self._now())
        return listed

    def chunk(self, entry: Entry, index: int) -> bytes:
        while not self._store.has(entry.key, index) and not self._fetched_unless_another_writer_has_it(entry, index):
            self._sleep(ANOTHER_WRITERS_CHUNK_IS_LOOKED_FOR_EVERY_S)
        return self._store.read(entry.key, index)

    def plan(self, owner: str, wanted: list[tuple[Entry, int]], *, being_read: bool = False) -> None:
        with self._lock:
            self._plans[owner] = deque(wanted)
            self._planned_files[owner] = frozenset(entry.key for entry, _ in wanted)
            (self._being_read.add if being_read else self._being_read.discard)(owner)
            self._work_arrived.notify_all()

    def keeping(self) -> set[str]:
        with self._lock:
            return set().union(*self._planned_files.values())

    def work_until_closed(self) -> None:
        while not self._closed:
            try:
                if self.work_one():
                    continue
            except Exception:
                logger.exception("A planned chunk could not be fetched")
                continue
            with self._lock:
                if not self._closed and not any(self._plans.values()):
                    self._work_arrived.wait()

    def close(self) -> None:
        with self._lock:
            self._closed = True
            self._work_arrived.notify_all()

    def work_one(self) -> bool:
        picked = self._next_wanted()
        if picked is None:
            return False
        self._fetched_unless_another_writer_has_it(*picked)
        return True

    def _next_wanted(self) -> tuple[Entry, int] | None:
        with self._lock:
            owners = sorted(self._plans, key=lambda owner: owner not in self._being_read)
            for owner in owners:
                wanted = self._plans[owner]
                while wanted:
                    entry, index = wanted.popleft()
                    if not self._store.has(entry.key, index):
                        self._plans[owner] = self._plans.pop(owner)
                        return entry, index
        return None

    def _fetched_unless_another_writer_has_it(self, entry: Entry, index: int) -> bool:
        claim = self._store.claim(entry.key, index)
        if claim is None:
            return False
        try:
            claim.write(self._downloaded(entry, index))
        except BaseException:
            claim.give_up()
            raise
        claim.keep()
        return True

    def _downloaded(self, entry: Entry, index: int) -> bytes:
        start = index * self._chunk_bytes
        stop = min(entry.size, start + self._chunk_bytes)
        for attempt in range(1, A_DOWNLOADS_ATTEMPTS):
            try:
                return self._span(entry, start, stop)
            except OSError:
                with self._lock:
                    self._links.pop(entry.fileid, None)
                self._sleep(attempt)
        return self._span(entry, start, stop)

    def _span(self, entry: Entry, start: int, stop: int) -> bytes:
        data = self._read(self._link(entry.fileid).url, start, stop)
        if len(data) != stop - start:
            raise WrongLength(f"{entry.path} answered {len(data)} bytes for {start}-{stop}")
        return data

    def _link(self, fileid: int) -> FileLink:
        with self._lock:
            link = self._links.get(fileid)
        if link is None or link.expires - self._now() < LINK_RENEWED_THIS_LONG_BEFORE_IT_EXPIRES_S:
            link = self._pcloud.file_link(fileid)
            with self._lock:
                self._links[fileid] = link
        return link

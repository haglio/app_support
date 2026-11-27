from __future__ import annotations

import json
import logging
import os
import threading
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from app_support import haglio_settings
from app_support.pcloud.api import PCloud, PCloudRefused
from app_support.pcloud.chunks import ChunkStore
from app_support.pcloud.fetching import CHUNK_BYTES, Entry, Fetcher, NotInPCloud
from app_support.pcloud.places import CloudPlaces
from app_support.pcloud.server import LoopbackServer
from app_support.threading_utils import start_daemon_thread

logger = logging.getLogger(__name__)

WORKERS = 3
PLAY_FROM_PCLOUD = "HAGLIO_PLAY_FROM_PCLOUD"
LOGIN_FILE = Path.home() / ".haglio" / "pcloud_login.json"
PCLOUD_DRIVE = "P:/"
_GIGABYTE = 1024 ** 3


@dataclass(frozen=True)
class Wish:
    path: Path
    spans: Callable[[Entry], list[tuple[int, int]]]


class PCloudLibrary:
    def __init__(self, places: CloudPlaces, fetcher: Fetcher, store: ChunkStore, *, chunk_bytes: int = CHUNK_BYTES,
                 cap_bytes: int, leave_free_bytes: int, workers: int = WORKERS) -> None:
        self._places, self._fetcher, self._store = places, fetcher, store
        self._chunk_bytes, self._cap_bytes, self._leave_free_bytes, self._workers = (
            chunk_bytes, cap_bytes, leave_free_bytes, workers)
        self._server = LoopbackServer(fetcher, chunk_bytes=chunk_bytes, local_copy_of=places.local_path_of)
        self._wished: dict[str, list[Wish]] = {}
        self._lock = threading.Lock()
        self._wishes_arrived = threading.Condition(self._lock)
        self._closed = False

    def __enter__(self) -> PCloudLibrary:
        self._server.__enter__()
        if self._workers:
            start_daemon_thread(target=self._plan_until_closed, name="pcloud-planner")
            for number in range(self._workers):
                start_daemon_thread(target=self._fetcher.work_until_closed, name=f"pcloud-fetcher-{number}")
        return self

    def __exit__(self, *_exc) -> None:
        with self._lock:
            self._closed = True
            self._wishes_arrived.notify_all()
        self._fetcher.close()
        self._server.__exit__()

    def playable(self, path: Path) -> str:
        cloud = self._places.cloud_path_of(path)
        return str(path) if cloud is None else self._server.url_for(cloud)

    def prefetch(self, owner: str, wishes: Sequence[Wish]) -> None:
        with self._lock:
            self._wished[owner] = list(wishes)
            self._wishes_arrived.notify_all()

    def plan_wished(self) -> None:
        with self._lock:
            wished, self._wished = self._wished, {}
        for owner, wishes in wished.items():
            self._fetcher.plan(owner, self._wanted(wishes))
        self._store.trim(cap_bytes=self._cap_bytes, keeping=self._fetcher.keeping(),
                         leave_free_bytes=self._leave_free_bytes)

    def fetch_one(self) -> bool:
        return self._fetcher.work_one()

    def _wanted(self, wishes: list[Wish]) -> list[tuple[Entry, int]]:
        wanted: list[tuple[Entry, int]] = []
        for wish in wishes:
            entry = self._entry_of(wish.path)
            if entry is None:
                continue
            last = (entry.size - 1) // self._chunk_bytes
            for start, stop in wish.spans(entry):
                for index in range(start // self._chunk_bytes,
                                   min(last, (max(start + 1, stop) - 1) // self._chunk_bytes) + 1):
                    if (entry, index) not in wanted:
                        wanted.append((entry, index))
        return wanted

    def _entry_of(self, path: Path) -> Entry | None:
        cloud = self._places.cloud_path_of(path)
        if cloud is None:
            return None
        try:
            return self._fetcher.entry(cloud)
        except NotInPCloud:
            return None

    def _plan_until_closed(self) -> None:
        while True:
            with self._lock:
                while not self._wished and not self._closed:
                    self._wishes_arrived.wait()
                if self._closed:
                    return
            try:
                self.plan_wished()
            except (PCloudRefused, OSError):
                logger.exception("Could not plan what to fetch from pCloud next")


def from_settings(*, environ: Mapping[str, str] = os.environ, settings: dict | None = None,
                  login_file: Path = LOGIN_FILE) -> PCloudLibrary | None:
    settings = haglio_settings.load() if settings is None else settings
    asked = settings.get("pcloud", {})
    if environ.get(PLAY_FROM_PCLOUD) != "1" and not asked.get("play_from_pcloud"):
        return None
    try:
        login = json.loads(login_file.read_text(encoding="utf-8"))
    except FileNotFoundError:
        logger.warning("Playing from pCloud was asked for, but this computer has not signed in to pCloud")
        return None
    store = ChunkStore(Path(asked.get("cache_folder") or Path.home() / ".haglio" / "pcloud_cache"))
    fetcher = Fetcher(PCloud(login["api_host"], auth=login["auth"]), store)
    return PCloudLibrary(CloudPlaces(asked.get("folders") or _folders_kept_in_pcloud(settings)), fetcher, store,
                         cap_bytes=int(asked.get("cache_gigabytes", 20) * _GIGABYTE),
                         leave_free_bytes=int(asked.get("leave_free_gigabytes", 10) * _GIGABYTE))


def _folders_kept_in_pcloud(settings: dict) -> dict[str, str]:
    root = Path(settings["library_root"])
    return {str(root): "/" + "/".join(root.parts[1:]), PCLOUD_DRIVE: "/"}

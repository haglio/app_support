from __future__ import annotations

import os
import shutil
import time
from collections.abc import Callable
from pathlib import Path

ABANDONED_AFTER_S = 60


class Claim:
    def __init__(self, partial: Path, kept: Path, now: Callable[[], float]) -> None:
        self._partial, self._kept, self._now = partial, kept, now
        self._stamp()

    def write(self, data: bytes) -> None:
        with self._partial.open("ab") as file:
            file.write(data)
        self._stamp()

    def keep(self) -> None:
        os.replace(self._partial, self._kept)

    def give_up(self) -> None:
        self._partial.unlink(missing_ok=True)

    def _stamp(self) -> None:
        moment = self._now()
        os.utime(self._partial, (moment, moment))


class ChunkStore:
    def __init__(self, folder: Path, *, now: Callable[[], float] = time.time,
                 remove: Callable[[Path], None] = Path.unlink,
                 free_bytes: Callable[[], int] | None = None) -> None:
        self._folder, self._now, self._remove = folder, now, remove
        self._free_bytes = free_bytes or (lambda: shutil.disk_usage(folder).free)

    def has(self, key: str, index: int) -> bool:
        return self._kept(key, index).is_file()

    def read(self, key: str, index: int) -> bytes:
        kept = self._kept(key, index)
        moment = self._now()
        os.utime(kept, (moment, moment))
        return kept.read_bytes()

    def claim(self, key: str, index: int) -> Claim | None:
        kept = self._kept(key, index)
        kept.parent.mkdir(parents=True, exist_ok=True)
        partial = kept.with_name(f"{index}.partial")
        if self._abandoned(partial):
            partial.unlink(missing_ok=True)
        try:
            partial.touch(exist_ok=False)
        except FileExistsError:
            return None
        return Claim(partial, kept, self._now)

    def trim(self, *, cap_bytes: int, keeping: set[str], leave_free_bytes: int = 0) -> None:
        held = [(path.stat(), path) for path in self._folder.glob("*/*") if path.suffix != ".partial"]
        total = sum(stat.st_size for stat, _ in held)
        allowed = min(cap_bytes, total + self._free_bytes() - leave_free_bytes)
        for stat, path in sorted(held, key=lambda found: found[0].st_mtime):
            if total <= allowed:
                return
            if path.parent.name not in keeping and self._removed(path):
                total -= stat.st_size

    def _removed(self, chunk: Path) -> bool:
        try:
            self._remove(chunk)
        except FileNotFoundError:
            return True
        except PermissionError:
            return False
        return True

    def _abandoned(self, partial: Path) -> bool:
        try:
            return self._now() - partial.stat().st_mtime > ABANDONED_AFTER_S
        except FileNotFoundError:
            return False

    def _kept(self, key: str, index: int) -> Path:
        return self._folder / key / str(index)

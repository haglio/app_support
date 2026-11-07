from __future__ import annotations

import json
import os
import time
from collections.abc import Callable
from pathlib import Path

from app_support.file_channel import read_whole, write_whole

LOCK_SUFFIX = ".lock"

_ONE_HOLD_TAKES_AT_MOST_S = 0.1
WAIT_S = 20 * _ONE_HOLD_TAKES_AT_MOST_S

_ERRING_LONG_IS_THE_SAFE_SIDE = 15
STALE_S = _ERRING_LONG_IS_THE_SAFE_SIDE * WAIT_S

_POLL_S = 0.005


def read_json(path: Path) -> dict:
    try:
        text = read_whole(path)
    except FileNotFoundError:
        return {}
    if not text.strip("\x00"):
        return {}
    payload = json.loads(text)
    if not isinstance(payload, dict):
        raise ValueError(f"{path} holds {type(payload).__name__}, not a JSON object")
    return payload


def read_json_or_empty(path: Path) -> dict:
    try:
        return read_json(path)
    except (OSError, ValueError):
        return {}


def _claim(lock: Path, *, wait_s: float, stale_s: float) -> int:
    deadline = time.monotonic() + wait_s
    while True:
        try:
            return os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            if _abandoned(lock, stale_s):
                # Windows refuses to unlink a lock another writer holds open through this handle, so a second taker
                # meets a PermissionError here rather than joining the first writer.
                lock.unlink(missing_ok=True)
                continue
            if time.monotonic() >= deadline:
                raise TimeoutError(f"{lock} was held for longer than {wait_s}s") from None
        except PermissionError:
            if time.monotonic() >= deadline:
                raise
        time.sleep(_POLL_S)


def _abandoned(lock: Path, stale_s: float) -> bool:
    try:
        return time.time() - lock.stat().st_mtime > stale_s
    except OSError:
        return False


def locked_update(
    path: Path,
    mutate: Callable[[dict], dict | None],
    *,
    wait_s: float = WAIT_S,
    stale_s: float = STALE_S,
) -> dict | None:
    lock = path.with_name(path.name + LOCK_SUFFIX)
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = _claim(lock, wait_s=wait_s, stale_s=stale_s)
    try:
        payload = mutate(read_json(path))
        if payload is None:
            return None
        write_whole(path, json.dumps(payload, indent=2) + "\n")
        return payload
    finally:
        os.close(handle)
        lock.unlink(missing_ok=True)

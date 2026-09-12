"""One small JSON document, read and rewritten by several processes at once.

Three apps write the video library's metadata sidecars: evolver's pipeline
stamps them on a ten-minute timer, a live Fun Time session strikes an act out of
one, and genau's clip matcher records which scene a clip came from.  Each did
its own read-then-write, so the second one to write erased the field the first
had just added -- both processes were holding a document read before the other's
edit, and neither could see the other.

A lock file beside the document closes that: the read, the change and the write
happen with nobody else in the file, and the write itself lands whole
(:func:`app_support.file_channel.write_whole`), so a reader that is not
updating still sees the old document or the new one and never half of either.
"""
from __future__ import annotations

import json
import os
import time
from collections.abc import Callable
from pathlib import Path

from app_support.file_channel import write_whole

LOCK_SUFFIX = ".lock"

# How long a writer waits for the holder to finish.  A hold is a read, a
# caller's edit to a dict and a rename -- milliseconds -- so two seconds is a
# queue of writers, not one slow one.
WAIT_S = 2.0

# When a lock is old enough that nothing living can be holding it.  Far longer
# than WAIT_S on purpose, and the two do not race: a live holder's lock is
# milliseconds old when the next writer arrives, so only a lock left by a
# process that died mid-update is already this old on arrival.  Erring long is
# the safe direction -- taking over a lock a slow holder still owns puts two
# writers in the document, which is the lost update this module exists to stop,
# while waiting too long only fails an update the caller can retry.
STALE_S = 30.0

_POLL_S = 0.005


def read_json(path: Path) -> dict:
    """*path*'s document, or an empty one when there is no file there.

    Absent is the ordinary first-run case and reads as empty.  Anything else
    that cannot be read as a JSON object raises, because this document belongs
    to several apps at once: reading a file we cannot parse as ``{}`` and then
    writing our own field into it replaces somebody else's record with ours.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {}
    payload = json.loads(text)
    if not isinstance(payload, dict):
        raise ValueError(f"{path} holds {type(payload).__name__}, not a JSON object")
    return payload


def _claim(lock: Path, *, wait_s: float, stale_s: float) -> int:
    """Create *lock* exclusively, waiting out whoever holds it.

    ``O_CREAT | O_EXCL`` is the whole mutex: the file system decides which of
    several creators wins, so no second writer can be inside on any platform the
    family runs on.  That stays true through a stale takeover -- the loser of a
    race to remove an abandoned lock still loses the race to recreate it.
    """
    deadline = time.monotonic() + wait_s
    while True:
        try:
            return os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            if _abandoned(lock, stale_s):
                # Whoever held this is gone; a live holder's lock is milliseconds
                # old.  Missing already means another writer got here first, which
                # is the same outcome.
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
    """Read *path*, hand the document to *mutate*, and write back what it returns.

    *mutate* returns the document to write, or ``None`` to write nothing -- a
    writer that decides on the spot it has no edit to make (the act was already
    struck out, the recorded scene is not the one being forgotten) leaves the
    file as it stands rather than rewriting it identically.  Whatever else it
    wants to report travels out through its own closure.

    Returns what was written, or ``None`` when *mutate* declined.  Raises
    ``TimeoutError`` when the lock could not be claimed: a lost update is
    silent, so a refused one must not be.
    """
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

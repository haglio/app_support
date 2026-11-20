from __future__ import annotations

import contextlib
import logging
import os
import threading
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum, auto
from pathlib import Path

from .file_held_alone import opened_alone

_ATTEMPTS_WHILE_HELD = 5
_DELAY_WHILE_HELD_S = 0.005
_ATTEMPTS_BEFORE_A_VERB_IS_LOST = 1000

_log = logging.getLogger(__name__)


def retried_while_held[T](
    act: Callable[[], T],
    *,
    attempts: int = _ATTEMPTS_WHILE_HELD,
    delay_s: float = _DELAY_WHILE_HELD_S,
) -> T:
    for _ in range(attempts - 1):
        try:
            return act()
        except PermissionError:
            time.sleep(delay_s)
    return act()


def publish_whole(
    path: Path,
    text: str,
    *,
    newline: str | None = None,
    attempts: int = _ATTEMPTS_WHILE_HELD,
    delay_s: float = _DELAY_WHILE_HELD_S,
) -> bool:
    """Rename-over publish; retried because Windows refuses to replace a file another process holds open.

    *newline* goes to ``open``: a ``csv`` writer terminates its own lines, so it passes "".
    """
    mine = path.with_suffix(f".{os.getpid()}.tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with mine.open("w", encoding="utf-8", newline=newline) as handle:
            handle.write(text)
    except OSError:
        return False
    try:
        retried_while_held(lambda: os.replace(mine, path), attempts=attempts, delay_s=delay_s)
    except OSError:
        with contextlib.suppress(OSError):
            mine.unlink(missing_ok=True)
        return False
    return True


def write_whole(
    path: Path,
    text: str,
    *,
    newline: str | None = None,
    attempts: int = _ATTEMPTS_WHILE_HELD,
    delay_s: float = _DELAY_WHILE_HELD_S,
) -> None:
    if not publish_whole(
        path, text, newline=newline, attempts=attempts, delay_s=delay_s
    ):
        raise OSError(f"could not replace {path}")


def read_whole(path: Path) -> str:
    return retried_while_held(lambda: path.read_text(encoding="utf-8"))


class _Try(Enum):
    WRITTEN = auto()
    HELD = auto()
    LOST = auto()


@dataclass
class _WaitingVerb:
    path: Path
    line: str
    attempts_left: int
    delay_s: float

    def tried_once(self) -> _Try:
        self.attempts_left -= 1
        try:
            _append_to(self.path, self.line)
        except PermissionError:
            if self.attempts_left > 0:
                return _Try.HELD
            _log_the_loss(self.path, self.line)
            return _Try.LOST
        except OSError:
            _log_the_loss(self.path, self.line)
            return _Try.LOST
        return _Try.WRITTEN


def _a_writer_that_outlives_the_caller(write_in_order: Callable[[], None]) -> None:
    threading.Thread(target=write_in_order, name="verbs in order", daemon=False).start()


class VerbSender:
    def __init__(
        self,
        *,
        sleep: Callable[[float], None] = time.sleep,
        start_writer: Callable[[Callable[[], None]], None] = _a_writer_that_outlives_the_caller,
    ) -> None:
        self._sleep = sleep
        self._start_writer = start_writer
        self._lock = threading.Lock()
        self._waiting: deque[_WaitingVerb] = deque()
        self._writing = False

    def append(
        self,
        path: Path,
        line: str,
        *,
        attempts: int = _ATTEMPTS_BEFORE_A_VERB_IS_LOST,
        delay_s: float = _DELAY_WHILE_HELD_S,
    ) -> bool:
        with self._lock:
            verb = _WaitingVerb(path, line, attempts, delay_s)
            if not self._waiting:
                tried = self._tried_on_the_callers_thread(verb)
                if tried is not _Try.HELD:
                    return tried is _Try.WRITTEN
            self._waiting.append(verb)
            if not self._writing:
                self._writing = True
                self._start_writer(self._write_in_order)
        return True

    def _tried_on_the_callers_thread(self, verb: _WaitingVerb) -> _Try:
        for attempt in range(_ATTEMPTS_WHILE_HELD):
            if attempt:
                self._sleep(verb.delay_s)
            tried = verb.tried_once()
            if tried is not _Try.HELD:
                return tried
        return _Try.HELD

    def _write_in_order(self) -> None:
        while True:
            with self._lock:
                if not self._waiting:
                    self._writing = False
                    return
                verb = self._waiting[0]
            if verb.tried_once() is _Try.HELD:
                self._sleep(verb.delay_s)
            else:
                with self._lock:
                    self._waiting.popleft()


_THE_SENDER = VerbSender()


def append_command(
    path: Path,
    line: str,
    *,
    attempts: int = _ATTEMPTS_BEFORE_A_VERB_IS_LOST,
    delay_s: float = _DELAY_WHILE_HELD_S,
) -> bool:
    return _THE_SENDER.append(path, line, attempts=attempts, delay_s=delay_s)


def _append_to(path: Path, line: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    _append_line(path, line)


def _log_the_loss(path: Path, line: str) -> None:
    _log.exception("Lost the command %r: could not append it to %s", line, path)


def _append_line(path: Path, line: str) -> None:
    with open(path, "a+", encoding="utf-8", opener=opened_alone) as handle:
        handle.seek(0, 2)
        if handle.tell():
            handle.seek(handle.tell() - 1)
            unterminated = handle.read(1) not in ("\n", "\r")
            handle.seek(0, 2)
            if unterminated:
                handle.write("\n")
        handle.write(line + "\n")


def _read_text(path: Path) -> str:
    """The text trimmed, without the BOM that Windows tools writing UTF-8 lead with."""
    return read_whole(path).replace("﻿", "").strip()


def consume_command_file(
    path: Path, *, logger: logging.Logger | None = None, uppercase: bool = True
) -> list[str]:
    claimed = path.with_suffix(path.suffix + ".consuming")
    try:
        if not path.exists():
            return []
        try:
            os.replace(path, claimed)
        except OSError:
            # Windows sharing violation: a writer holds the file.
            return []
        text = _read_text(claimed)
        claimed.unlink(missing_ok=True)
        if uppercase:
            text = text.upper()
        if not text:
            return []
        return [line.strip() for line in text.splitlines() if line.strip()]
    except Exception:
        if logger is not None:
            logger.exception("Failed to consume command file %s", path)
        return []


def read_flag(path: Path, *, default: bool, logger: logging.Logger | None = None) -> bool:
    try:
        if not path.exists():
            return default
        text = _read_text(path)
    except Exception:
        if logger is not None:
            logger.exception("Failed to read flag file %s", path)
        return default
    if text == "1":
        return True
    if text == "0":
        return False
    return default


def write_flag(
    path: Path,
    value: bool,
    *,
    attempts: int = _ATTEMPTS_WHILE_HELD,
    delay_s: float = _DELAY_WHILE_HELD_S,
) -> bool:
    return publish_whole(path, "1" if value else "0", attempts=attempts, delay_s=delay_s)


def read_paused_state(path: Path, *, logger: logging.Logger | None = None) -> bool:
    return read_flag(path, default=False, logger=logger)


def publish_stamp(
    path: Path,
    now: float | None = None,
    *,
    attempts: int = _ATTEMPTS_WHILE_HELD,
    delay_s: float = _DELAY_WHILE_HELD_S,
) -> bool:
    stamp = time.time() if now is None else now
    return publish_whole(path, str(stamp), attempts=attempts, delay_s=delay_s)


def stamp_age(path: Path, now: float | None = None) -> float | None:
    try:
        if not path.exists():
            return None
        stamped = float(_read_text(path))
    except (OSError, ValueError):
        return None
    return (time.time() if now is None else now) - stamped


def read_key_values(path: Path) -> dict[str, str]:
    return dict(
        line.split("=", 1)
        for line in read_whole(path).splitlines()
        if "=" in line
    )

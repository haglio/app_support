from __future__ import annotations

import logging
import os
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_INTERVAL_SECONDS = 900.0

_MARKER_DIR = ("app_support", "peer-watch")

log = logging.getLogger(__name__)


def _stand_down_marker(key: str, environ: Mapping[str, str]) -> Path:
    base = environ.get("LOCALAPPDATA") or Path.home()
    return Path(base).joinpath(*_MARKER_DIR) / f"{key}.txt"


def stand_down(key: str, *, environ: Mapping[str, str] = os.environ) -> None:
    marker = _stand_down_marker(key, environ)
    try:
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text(
            f"{time.strftime('%Y-%m-%d %H:%M:%S')} closed on purpose; peers leave "
            "it down until it is started again\n",
            encoding="utf-8",
        )
    except OSError:
        log.exception("Could not write the stand-down marker %s", marker)


def clear_stand_down(key: str, *, environ: Mapping[str, str] = os.environ) -> None:
    marker = _stand_down_marker(key, environ)
    try:
        marker.unlink(missing_ok=True)
    except OSError:
        log.exception("Could not clear the stand-down marker %s", marker)


def is_stood_down(key: str, *, environ: Mapping[str, str] = os.environ) -> bool:
    try:
        return _stand_down_marker(key, environ).exists()
    except OSError:
        return False


@dataclass(frozen=True)
class Surroundings:
    interval_seconds: float = DEFAULT_INTERVAL_SECONDS
    now: Callable[[], float] = time.monotonic
    environ: Mapping[str, str] = field(default_factory=lambda: os.environ)


_THIS_COMPUTER = Surroundings()


class PeerWatch:
    def __init__(
        self,
        *,
        peer_key: str,
        is_up: Callable[[], bool],
        launch: Callable[[], None],
        logger: logging.Logger | None = None,
        surroundings: Surroundings = _THIS_COMPUTER,
    ):
        self._peer_key = peer_key
        self._is_up = is_up
        self._launch = launch
        self._interval = surroundings.interval_seconds
        self._now = surroundings.now
        self._log = logger or log
        self._environ = surroundings.environ
        self._checked_at: float | None = None

    def _is_due(self) -> bool:
        return self._checked_at is None or self._now() - self._checked_at >= self._interval

    def tick(self) -> None:
        if not self._is_due():
            return
        self._checked_at = self._now()
        try:
            if self._is_up():
                return
            if is_stood_down(self._peer_key, environ=self._environ):
                self._log.debug("%s is down but stood down; leaving it", self._peer_key)
                return
            self._log.info("%s is not running; starting it", self._peer_key)
            self._launch()
        except Exception:
            self._log.exception("Peer watch for %s failed", self._peer_key)

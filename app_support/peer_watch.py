"""Two long-running processes keeping each other alive, and the veto over it.

A desktop app that is supposed to be up all the time needs something watching
it, and whatever watches it needs something watching *that*.  A pair of apps
that each watch the other ends the regress without a third process: whichever
one is alive notices the other is gone and starts it again, and the only way to
lose both at once is to lose the machine -- which is a reboot, where each app's
own start-up arrangements take over.

The revival is worth nothing without the veto beside it.  An app that comes back
a quarter of an hour after the user deliberately closed it is not a supervised
app, it is one that argues; so a deliberate quit leaves a **stand-down marker**,
and a watcher honors any marker it finds.  Every *other* way an app dies --
killed from the task list, a crash, quitting itself on a session-end event that
was then cancelled -- leaves no marker and is revived.  That is the distinction
this module exists to draw: not "is it down?" but "is it down because somebody
wanted it down?".

The marker is a file because the process that wrote it is gone by the time it
matters, and it lives under ``LOCALAPPDATA`` because that is per-user, local to
the machine, and outside every project tree -- some of which sit under a
file-sync service that renames files out from under a running app.

**The path convention is spelled here, once, on purpose.**  The writer and the
reader are two different applications with no import between them, so a
convention each spelled for itself would drift, and a drifted marker does not
announce itself: the watcher simply finds no marker and revives an app the user
had just closed.  Nothing here knows which applications these are -- a key is
whatever string the two sides agree to call one of them.
"""
from __future__ import annotations

import logging
import os
import time
from collections.abc import Callable, Mapping
from pathlib import Path

# Fifteen minutes.  Long enough that the checking costs nothing, short enough
# that the worst case -- an app that died the second after a check -- is a
# quarter hour of lost work rather than the overnight one this replaces.  A
# default rather than a constant each caller repeats, so the two sides of a pair
# cannot end up polling at rates that differ for no reason anybody wrote down.
DEFAULT_INTERVAL_SECONDS = 900.0

_MARKER_DIR = ("app_support", "peer-watch")

log = logging.getLogger(__name__)


def _stand_down_marker(key: str, environ: Mapping[str, str]) -> Path:
    """The marker file for *key* -- the name the two sides of a pair agree on.

    ``LOCALAPPDATA`` is the real base; the home directory is what is left when a
    test or a non-Windows import has no such variable, which keeps this
    importable everywhere rather than raising on a machine that is only
    collecting the suite.
    """
    base = environ.get("LOCALAPPDATA") or Path.home()
    return Path(base).joinpath(*_MARKER_DIR) / f"{key}.txt"


def stand_down(key: str, *, environ: Mapping[str, str] = os.environ) -> None:
    """Record that *key* was closed on purpose, so peers leave it alone.

    Best-effort, and deliberately so: this runs on the way out of a quit the user
    asked for, and a quit that fails because a directory could not be made is a
    worse outcome than a peer that revives something once.  The contents are for
    a human reading back afterwards; only the file's existence is ever tested.
    """
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
    """Forget any stand-down for *key*.

    Called by the app itself as it starts: being launched at all is the user
    saying they want it up, whatever they wanted the last time they closed it.
    """
    marker = _stand_down_marker(key, environ)
    try:
        marker.unlink(missing_ok=True)
    except OSError:
        log.exception("Could not clear the stand-down marker %s", marker)


def is_stood_down(key: str, *, environ: Mapping[str, str] = os.environ) -> bool:
    """Whether *key* was closed on purpose and has not been started since.

    An unreadable state directory answers "no".  The alternative is a filesystem
    problem that quietly stops an app being supervised at all, which is the
    failure this whole module exists to prevent.
    """
    try:
        return _stand_down_marker(key, environ).exists()
    except OSError:
        return False


class PeerWatch:
    """Start a peer that is gone, no more often than *interval_seconds*.

    Built around a ``tick`` a caller may run at whatever cadence it already has:
    a host with a five-second watchdog of its own passes every beat through here
    and the throttle keeps the real checking to the interval.  The first tick
    always checks -- a peer already down at start-up should not have to wait out
    a full interval to be noticed.

    ``is_up`` is asked first and is expected to be cheap and certain: a named
    mutex, not a process scan.  ``launch`` is only ever called for a peer that
    answered no, and it must be safe to call over a live peer anyway, because
    between the two there is a window in which the peer can come up on its own --
    so both sides of a pair lean on their own single-instance guard to absorb a
    duplicate launch.  Nothing here ever kills anything: the worst a misread
    costs is one process that exits immediately, where killing first could not
    be taken back.
    """

    def __init__(
        self,
        *,
        peer_key: str,
        is_up: Callable[[], bool],
        launch: Callable[[], None],
        interval_seconds: float = DEFAULT_INTERVAL_SECONDS,
        now: Callable[[], float] = time.monotonic,
        logger: logging.Logger | None = None,
        environ: Mapping[str, str] = os.environ,
    ):
        self._peer_key = peer_key
        self._is_up = is_up
        self._launch = launch
        self._interval = interval_seconds
        self._now = now
        self._log = logger or log
        self._environ = environ
        self._checked_at: float | None = None

    def _is_due(self) -> bool:
        return self._checked_at is None or self._now() - self._checked_at >= self._interval

    def tick(self) -> None:
        """One beat, and never an exception.

        The caller is a live application's own timer, and the peer is not that
        application's job: a state directory that has gone away, or a launcher
        that has been renamed, must cost this check and never the process doing
        it.  The stamp is taken before the work rather than after, so a launcher
        that fails every time is retried on the interval and not on every beat.
        """
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

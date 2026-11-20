from __future__ import annotations

import os
import sys
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path

from app_support import processes, win32

LIVE_SESSION = "Local\\Haglio.LiveSession"


def _this_process_desktop() -> str | None:
    return processes.desktop_of(os.getpid())


def _checkout_of_this_program() -> Path | None:
    started_as = getattr(sys.modules.get("__main__"), "__file__", None) or (sys.argv[0] if sys.argv else "")
    if not started_as:
        return None
    return next((folder for folder in Path(started_as).resolve().parents if (folder / ".git").exists()), None)


def _is_a_preview(checkout: Path | None) -> bool:
    return checkout is not None and (checkout / ".git").is_file()


def is_live(*, is_held: Callable[[str], bool] = win32.is_mutex_held) -> bool:
    return is_held(LIVE_SESSION)


@contextmanager
def holding_a_live_session(*, desktop: Callable[[], str | None] = _this_process_desktop,
                           checkout: Callable[[], Path | None] = _checkout_of_this_program,
                           share: Callable[[str], int | None] = win32.share_mutex,
                           release: Callable[[int], None] = win32.release_mutex) -> Iterator[None]:
    his_session = processes.whose(desktop()) == processes.HIS and not _is_a_preview(checkout())
    handle = share(LIVE_SESSION) if his_session else None
    try:
        yield
    finally:
        if handle:
            release(handle)

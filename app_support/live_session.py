from __future__ import annotations

import os
from collections.abc import Callable, Iterator
from contextlib import contextmanager

from app_support import processes, win32

LIVE_SESSION = "Local\\Haglio.LiveSession"


def _this_process_desktop() -> str | None:
    return processes.desktop_of(os.getpid())


def is_live(*, is_held: Callable[[str], bool] = win32.is_mutex_held) -> bool:
    return is_held(LIVE_SESSION)


@contextmanager
def holding_a_live_session(*, desktop: Callable[[], str | None] = _this_process_desktop,
                           share: Callable[[str], int | None] = win32.share_mutex,
                           release: Callable[[int], None] = win32.release_mutex) -> Iterator[None]:
    on_his_desktop = processes.whose(desktop()) == processes.HIS
    handle = share(LIVE_SESSION) if on_his_desktop else None
    try:
        yield
    finally:
        if handle:
            release(handle)

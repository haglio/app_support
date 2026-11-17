from __future__ import annotations

import threading
import time
from collections.abc import Callable


def start_daemon_thread(
    *,
    target: Callable,
    args: tuple = (),
    kwargs: dict | None = None,
    name: str | None = None,
) -> threading.Thread:
    thread = threading.Thread(target=target, args=args, kwargs=kwargs or {}, daemon=True, name=name)
    thread.start()
    return thread


def wait_until(
    predicate: Callable[[], object],
    *,
    timeout: float | None = None,
    interval: float = 0.01,
    now: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
    pump: Callable[[], object] = lambda: None,
) -> None:
    deadline = None if timeout is None else now() + timeout
    while True:
        if predicate():
            return
        remaining = interval if deadline is None else deadline - now()
        if remaining <= 0:
            name = getattr(predicate, "__qualname__", None) or repr(predicate)
            raise TimeoutError(f"{name} did not become true within {timeout}s")
        pump()
        sleep(min(interval, remaining))

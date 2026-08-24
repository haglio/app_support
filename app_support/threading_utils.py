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
    timeout: float,
    interval: float = 0.01,
    now: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> None:
    """Block until ``predicate()`` is truthy, or raise ``TimeoutError`` trying.

    Waiting on a thread or a child process by sleeping a fixed number of seconds
    pays that whole nap on every machine and still goes red on a loaded one.
    Polling the thing itself returns the moment it happens, and spends the
    timeout only when it never does. The error names the predicate, so a wait
    that does time out says which one.

    The last poll happens at the deadline rather than before it — the work often
    lands during the final nap — and no nap runs past it. ``now`` and ``sleep``
    are injectable so this helper's own tests need no real clock; callers who
    want the real one leave them alone.
    """
    deadline = now() + timeout
    while True:
        if predicate():
            return
        remaining = deadline - now()
        if remaining <= 0:
            name = getattr(predicate, "__qualname__", None) or repr(predicate)
            raise TimeoutError(f"{name} did not become true within {timeout}s")
        sleep(min(interval, remaining))

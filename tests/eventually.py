"""Waiting for what another process does, as long as it may take and no longer."""
from __future__ import annotations

import time


def eventually(condition, within_s: float = 15.0) -> bool:
    deadline = time.monotonic() + within_s
    while time.monotonic() < deadline:
        if condition():
            return True
        time.sleep(0.1)
    return False

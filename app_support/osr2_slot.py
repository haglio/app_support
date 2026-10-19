"""The one way to the OSR2: a sender connects to the broker on
:data:`app_support.ports.OSR2_SLOT`, says its name on the first line, then sends
T-Code, one line at a time, spelled once for the broker and every sender."""
from __future__ import annotations

__all__ = ["hello", "read_hello"]


def hello(sender: str) -> bytes:
    return f"{sender.lower()}\n".encode("ascii")


def read_hello(line: bytes | str) -> str:
    if isinstance(line, bytes):
        line = line.decode("ascii", errors="replace")
    return line.strip().casefold()

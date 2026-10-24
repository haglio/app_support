"""The one way to the OSR2: a sender connects to the broker on
:data:`app_support.ports.OSR2_SLOT`, says its name on the first line, then sends
T-Code, one line at a time; when another sender or a hold takes the OSR2, the
broker says so before it hangs up. Spelled once for the broker and every sender."""
from __future__ import annotations

__all__ = ["TAKEN", "hello", "read_hello", "says_it_was_taken"]

TAKEN = b"taken\n"


def hello(sender: str) -> bytes:
    return f"{sender.lower()}\n".encode("ascii")


def read_hello(line: bytes | str) -> str:
    if isinstance(line, bytes):
        line = line.decode("ascii", errors="replace")
    return line.strip().casefold()


def says_it_was_taken(received: bytes) -> bool:
    return TAKEN in received

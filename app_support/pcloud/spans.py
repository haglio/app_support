from __future__ import annotations


def asked_span(header: str | None, size: int) -> tuple[int, int]:
    if not header:
        return 0, size
    first, _, last = header.removeprefix("bytes=").partition("-")
    if not first:
        return max(0, size - int(last)), size
    return int(first), min(size, int(last) + 1) if last else size

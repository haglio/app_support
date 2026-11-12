from __future__ import annotations

GENAU_FLICK = "genau_flick"
EXCERPT = "excerpt"
FULL_LENGTH = "full_length"

TYPES = (GENAU_FLICK, EXCERPT, FULL_LENGTH)

EXCERPT_MAX_SECONDS = 10.0


def free_kind(*, genau: bool, excerpt: bool) -> str:
    if genau:
        return GENAU_FLICK
    if excerpt:
        return EXCERPT
    return ""


def classify(*, genau: bool, excerpt: bool, duration_seconds: float | None) -> str:
    free = free_kind(genau=genau, excerpt=excerpt)
    if free:
        return free
    if duration_seconds is not None and duration_seconds <= EXCERPT_MAX_SECONDS:
        return EXCERPT
    return FULL_LENGTH

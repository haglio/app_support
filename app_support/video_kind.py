from __future__ import annotations

GENAU_FLICK = "genau_flick"
CLIP = "excerpt"
FULL_LENGTH = "full_length"

TYPES = (GENAU_FLICK, CLIP, FULL_LENGTH)

CLIP_MAX_SECONDS = 10.0


def free_kind(*, genau: bool, clip: bool) -> str:
    if genau:
        return GENAU_FLICK
    if clip:
        return CLIP
    return ""


def classify(*, genau: bool, clip: bool, duration_seconds: float | None) -> str:
    free = free_kind(genau=genau, clip=clip)
    if free:
        return free
    if duration_seconds is not None and duration_seconds <= CLIP_MAX_SECONDS:
        return CLIP
    return FULL_LENGTH

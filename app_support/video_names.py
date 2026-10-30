"""What a video's file name and its metadata record say it is.

Evolver writes both -- it appends the models that processed a video to the name,
and records the scene a clip shows -- and Fun Time reads them, so the rule is one
format the two agree on, kept where both read it.
"""
from __future__ import annotations

import re

SEPARATORS = re.compile(r"[-_ .]+")

QUALITY_TOKENS = frozenset({
    "topaz", "iris2", "old_iris2", "upscale", "upscaled", "remux",
    "x264", "x265", "hevc", "av1",
    "60fps", "30fps", "24fps",
    "480p", "540", "540p", "720p", "1080p", "1440p", "2160p", "4k",
    "mp4", "mkv", "web", "webrip",
})

_QUALITY_TOKENS_HOLDING_A_SEPARATOR = tuple(token for token in QUALITY_TOKENS if "_" in token)

_HASH_TOKEN = re.compile(r"[a-z0-9]{6,12}")

PROCESSING_SUFFIXES = (
    "_topaz_cfr",
    "_topaz",
    "_gcg5",
    "_prob4",
    "_ghq5",
    "_iris3",
    "_iris2",
    "_apf2",
    "_apo8",
    "_enh",
)


def strip_processing_suffixes(stem: str) -> str:
    while True:
        stripped = next((stem[: -len(suffix)] for suffix in PROCESSING_SUFFIXES if stem.endswith(suffix)), stem)
        if stripped == stem:
            return stem
        stem = stripped


def _is_hash_token(token: str) -> bool:
    return bool(_HASH_TOKEN.fullmatch(token)) and any(c.isalpha() for c in token) and any(
        c.isdigit() for c in token)


def normalize_title(stem: str) -> str:
    text = stem.lower()
    for token in _QUALITY_TOKENS_HOLDING_A_SEPARATOR:
        text = text.replace(token, " ")
    tokens = [token for token in SEPARATORS.split(text) if token and token not in QUALITY_TOKENS]
    while tokens and _is_hash_token(tokens[-1]):
        tokens.pop()
    return " ".join(tokens)


def stable_title(stem: str) -> str:
    return normalize_title(strip_processing_suffixes(stem))


def clip_title(payload: dict) -> str:
    clip = payload.get("clip")
    if not isinstance(clip, dict):
        return ""
    parts = (str(clip.get(field, "") or "").strip() for field in ("performer", "source"))
    return " - ".join(part for part in parts if part)


def version_group_of(payload: dict) -> str:
    version = payload.get("version")
    if not isinstance(version, dict):
        return ""
    return str(version.get("group") or "")

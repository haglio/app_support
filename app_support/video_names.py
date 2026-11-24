from __future__ import annotations

import re
from pathlib import PurePath

from app_support.comfy_file_refs import frame_name

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

UPSCALE_SUFFIX = "_topaz"

PROCESSING_SUFFIXES = (
    f"{UPSCALE_SUFFIX}_cfr",
    UPSCALE_SUFFIX,
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


_COPY_COUNT = re.compile(r" \(\d+\)$")


def strip_uniquifier(stem: str) -> str:
    return _COPY_COUNT.sub("", stem)


def stem_as_made(path) -> str:
    stem = PurePath(frame_name(str(path))).stem
    while True:
        earlier = strip_uniquifier(stem).removesuffix(UPSCALE_SUFFIX)
        if earlier == stem:
            return stem
        stem = earlier


SOUND_MARK = "-audio"


def stem_of_either_copy(path) -> str:
    return stem_as_made(path).removesuffix(SOUND_MARK)


def origin_stem(stem: str) -> str:
    while True:
        reduced = strip_processing_suffixes(strip_uniquifier(stem))
        if reduced == stem:
            return stem
        stem = reduced


def generation_stem(stem: str) -> str:
    while True:
        made = origin_stem(stem).removesuffix(SOUND_MARK).rstrip("_")
        if made == stem:
            return stem
        stem = made


def _is_an_id(token: str) -> bool:
    return bool(_HASH_TOKEN.fullmatch(token)) and any(c.isdigit() for c in token)


def _is_hash_token(token: str) -> bool:
    return _is_an_id(token) and any(c.isalpha() for c in token)


def normalize_title(stem: str) -> str:
    text = stem.lower()
    for token in _QUALITY_TOKENS_HOLDING_A_SEPARATOR:
        text = text.replace(token, " ")
    every_token = [token for token in SEPARATORS.split(text) if token]
    tokens = [token for token in every_token if token not in QUALITY_TOKENS]
    if _is_a_word_and_the_id_a_site_named_it_by(every_token, tokens):
        return " ".join(tokens)
    while tokens and _is_hash_token(tokens[-1]):
        tokens.pop()
    return " ".join(tokens)


def _is_a_word_and_the_id_a_site_named_it_by(every_token: list[str], tokens: list[str]) -> bool:
    return every_token[:2] == tokens and is_named_by_its_id(" ".join(tokens))


def is_named_by_its_id(title: str) -> bool:
    words = title.split()
    return len(words) == 2 and _is_an_id(words[1])


def stable_title(stem: str) -> str:
    return normalize_title(strip_processing_suffixes(stem))


def clip_title(payload: dict) -> str:
    clip = payload.get("clip")
    if not isinstance(clip, dict):
        return ""
    parts = (str(clip.get(field, "") or "").strip() for field in ("performer", "source"))
    return " - ".join(part for part in parts if part)


FULL_VIDEO_ID_FIELD = "full_video_id"


def full_video_id_of(payload: dict) -> str | None:
    clip = payload.get("clip")
    given = clip.get(FULL_VIDEO_ID_FIELD) if isinstance(clip, dict) else None
    return given if isinstance(given, str) and given else None


def version_group_of(payload: dict) -> str:
    version = payload.get("version")
    if not isinstance(version, dict):
        return ""
    return str(version.get("group") or "")



TITLE_FIELD = "title"


def title_while_playing(payload: dict, video) -> str:
    evolvers_name_for_the_movie_and_its_cast = str(payload.get(TITLE_FIELD, "") or "").strip()
    return (
        evolvers_name_for_the_movie_and_its_cast
        or clip_title(payload)
        or version_group_of(payload)
        or PurePath(video).stem
    )

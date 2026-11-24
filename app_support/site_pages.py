from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import quote

from app_support.local_time import when_words

_IMAGE_SETTINGS = [
    ("Model", "model"),
    ("Resolution", "resolution"),
    ("Aspect ratio", "aspect_ratio"),
    ("Quality", "quality"),
    ("Style", "style"),
    ("Creativity", "creativity"),
    ("Seed", "seed"),
    ("Created", "created"),
]
_VIDEO_SETTINGS = [
    ("Model", "model"),
    ("Action", "action"),
    ("Resolution", "resolution"),
    ("Aspect ratio", "aspect_ratio"),
    ("Quality", "quality"),
    ("Seed", "seed"),
    ("Created", "created"),
]


def _named_settings(made: dict, names: list[tuple[str, str]]) -> list[list[str]]:
    return [[label, _as_shown(key, str(made[key]))] for label, key in names if made.get(key)]


def _as_shown(key: str, setting: str) -> str:
    return when_words(setting) if key == "created" else setting


def settings_for_the_page(record: dict) -> dict:
    video = record.get("video") or {}
    image = record.get("source_image") or None
    if image:
        return {
            "kind": "image",
            "positive": image.get("positive_prompt", ""),
            "negative": image.get("negative_prompt", ""),
            "settings": _named_settings(image, _IMAGE_SETTINGS),
            "video_prompt": video.get("prompt", ""),
            "video_settings": _named_settings(video, _VIDEO_SETTINGS),
        }
    return {
        "kind": "video",
        "positive": video.get("prompt", ""),
        "negative": "",
        "settings": _named_settings(video, _VIDEO_SETTINGS),
        "video_prompt": "",
        "video_settings": [],
    }


def page_address(record: dict, *, video_page: str, image_page: str, submit: bool = False) -> str:
    settings = settings_for_the_page(record)
    page = image_page if settings["kind"] == "image" else video_page
    if submit:
        settings["submit"] = True
    return f"{page}#ft={quote(json.dumps(settings, ensure_ascii=False, separators=(',', ':')))}"


FILL_SCRIPT = Path("fun_time") / "static" / "regen_autofill.user.js"


def fill_script(fun_time_checkouts: list[Path]) -> Path | None:
    return next((script for checkout in fun_time_checkouts
                 if (script := checkout / FILL_SCRIPT).is_file()), None)

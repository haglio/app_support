from __future__ import annotations

import json
import logging
from pathlib import Path

from app_support.file_channel import read_whole, write_whole

logger = logging.getLogger(__name__)

VERSION = "1.0"

RANGE = 100


def document(
    actions: list[dict], *, duration_seconds: int, creator: str = ""
) -> dict:
    return {
        "actions": sorted(actions, key=lambda action: action["at"]),
        "inverted": False,
        "metadata": {
            "bookmarks": [],
            "chapters": [],
            "creator": creator,
            "description": "",
            "duration": duration_seconds,
            "license": "",
            "notes": "",
            "performers": [],
            "script_url": "",
            "tags": [],
            "title": "",
            "type": "basic",
            "video_url": "",
        },
        "range": RANGE,
        "version": VERSION,
    }


def actions_of(payload: dict) -> list[dict]:
    actions = payload.get("actions")
    return actions if isinstance(actions, list) else []


def read(path: Path) -> dict:
    try:
        payload = json.loads(read_whole(Path(path)))
    except FileNotFoundError:
        return {}
    except (OSError, json.JSONDecodeError):
        logger.warning("Unreadable funscript %s", path, exc_info=True)
        return {}
    if not isinstance(payload, dict):
        logger.warning(
            "%s holds %s, not a funscript document", path, type(payload).__name__
        )
        return {}
    return payload


def read_actions(path: Path | None) -> list[dict]:
    return actions_of(read(path)) if path is not None else []


def write(path: Path, payload: dict) -> None:
    write_whole(Path(path), json.dumps(payload))

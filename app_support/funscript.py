from __future__ import annotations

import json
import logging
from pathlib import Path

from app_support.file_channel import read_whole, write_whole
from app_support.mirrored_tree import mirrored_path

logger = logging.getLogger(__name__)

VERSION = "1.0"

POS_RUNS_FROM_0_TO = 100

ACTIONS = "actions"
AT = "at"
METADATA = "metadata"
DURATION = "duration"
BOOKMARKS = "bookmarks"
CHAPTERS = "chapters"

EXTENSION = ".funscript"
_GENERATED_MARK_EXTENSION = ".generated"
_SCRIPTS_TREE = Path("scripts", "scripts")
_GENERATED_MARKS_TREE = Path("scripts", "generated")


def document(
    actions: list[dict], *, duration_seconds: int, creator: str = ""
) -> dict:
    return {
        ACTIONS: sorted(actions, key=lambda action: action[AT]),
        "inverted": False,
        METADATA: {
            BOOKMARKS: [],
            CHAPTERS: [],
            "creator": creator,
            "description": "",
            DURATION: duration_seconds,
            "license": "",
            "notes": "",
            "performers": [],
            "script_url": "",
            "tags": [],
            "title": "",
            "type": "basic",
            "video_url": "",
        },
        "range": POS_RUNS_FROM_0_TO,
        "version": VERSION,
    }


def actions_of(payload: dict) -> list[dict]:
    actions = payload.get(ACTIONS)
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


def scripts_tree_in(trees_beside: Path) -> Path:
    return Path(trees_beside) / _SCRIPTS_TREE


def generated_marks_tree_in(trees_beside: Path) -> Path:
    return Path(trees_beside) / _GENERATED_MARKS_TREE


def script_of(video: Path, *, library: Path, scripts_tree: Path) -> Path | None:
    return mirrored_path(video, roots=(library,), mirror_root=scripts_tree, suffix=EXTENSION)


def generated_mark_of(script: Path, *, scripts_tree: Path, marks_tree: Path) -> Path | None:
    return mirrored_path(script, roots=(scripts_tree,), mirror_root=marks_tree, suffix=_GENERATED_MARK_EXTENSION)

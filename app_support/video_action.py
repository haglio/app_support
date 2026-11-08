from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from app_support.json_store import locked_update

VIDEO_BLOCK = "video"
SITE_ACTION_KEY = "action"
WRONG_ACTION_KEY = "wrong_action"
STORED_ACTIONS_KEY = "labels"


def strike(record_path: Path) -> str:
    record_path = Path(record_path)
    if not record_path.exists():
        return ""
    struck = ""

    def struck_out(record: dict) -> dict | None:
        nonlocal struck
        video = record.get(VIDEO_BLOCK)
        if not isinstance(video, dict):
            return None
        struck = str(video.pop(SITE_ACTION_KEY, "") or "").strip()
        if not struck:
            return None
        video[WRONG_ACTION_KEY] = struck
        return record

    try:
        locked_update(record_path, struck_out)
    except ValueError:
        return ""
    return struck


def actions_of(record: dict) -> tuple[str, ...]:
    video = record.get(VIDEO_BLOCK)
    actions = video.get(STORED_ACTIONS_KEY) if isinstance(video, dict) else None
    return tuple(actions) if isinstance(actions, list) else ()


def with_actions(record: dict, actions: Sequence[str]) -> dict | None:
    video = record.get(VIDEO_BLOCK, {})
    if not isinstance(video, dict) or actions_of(record) == tuple(actions):
        return None
    others = {key: value for key, value in video.items() if key != STORED_ACTIONS_KEY}
    return {**record, VIDEO_BLOCK: others | ({STORED_ACTIONS_KEY: list(actions)} if actions else {})}


ACTION_KEY = SITE_ACTION_KEY
LABELS_KEY = STORED_ACTIONS_KEY
labels_of = actions_of
labeled = with_actions

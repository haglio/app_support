from __future__ import annotations

from pathlib import Path

from app_support.json_store import locked_update

VIDEO_BLOCK = "video"
ACTION_KEY = "action"
WRONG_ACTION_KEY = "wrong_action"


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
        struck = str(video.pop(ACTION_KEY, "") or "").strip()
        if not struck:
            return None
        video[WRONG_ACTION_KEY] = struck
        return record

    try:
        locked_update(record_path, struck_out)
    except ValueError:
        return ""
    return struck

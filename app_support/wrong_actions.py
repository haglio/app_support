from __future__ import annotations

from pathlib import Path

from app_support import haglio_settings, siblings
from app_support.json_store import locked_update

FILE_NAME = "wrong_actions.json"
SAID = "said"


def origenerators_state() -> Path:
    return siblings.project_dir("origenerator", haglio_settings.project_roots()) / "state"


def _file(state_dir) -> Path:
    return Path(state_dir) / FILE_NAME


def _said_in(held: dict) -> list[str]:
    said = held.get(SAID)
    return [video for video in said if isinstance(video, str)] if isinstance(said, list) else []


def _updated(state_dir, change) -> dict | None:
    def changed(held: dict) -> dict | None:
        return change(_said_in(held))

    try:
        return locked_update(_file(state_dir), changed)
    except ValueError:
        _file(state_dir).unlink(missing_ok=True)
        return locked_update(_file(state_dir), lambda _damaged: change([]))


def say(state_dir, video) -> None:
    video = str(video)
    _updated(state_dir, lambda said: None if video in said else {SAID: [*said, video]})


def take(state_dir) -> tuple[str, ...]:
    if not _file(state_dir).is_file():
        return ()
    taken: list[str] = []

    def emptied(said: list[str]) -> dict | None:
        taken.extend(said)
        return {SAID: []} if said else None

    _updated(state_dir, emptied)
    return tuple(taken)

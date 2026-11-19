from __future__ import annotations

from pathlib import Path

from .file_channel import publish_whole, read_whole
from .state_files import OSR2_TURN_OFF_REMINDER

__all__ = ["remind_to_turn_off", "what_closed"]


def remind_to_turn_off(broker_state_dir: Path, *, closed: str) -> bool:
    return publish_whole(Path(broker_state_dir) / OSR2_TURN_OFF_REMINDER, closed)


def what_closed(broker_state_dir: Path) -> str | None:
    asked = Path(broker_state_dir) / OSR2_TURN_OFF_REMINDER
    try:
        closed = read_whole(asked).strip()
        asked.unlink()
    except FileNotFoundError:
        return None
    return closed or None

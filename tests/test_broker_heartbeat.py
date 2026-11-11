from __future__ import annotations

from pathlib import Path

from app_support import broker_heartbeat, state_files
from app_support.file_channel import publish_stamp


def _stamped(state_dir: Path, seconds_ago: float, now: float = 1000.0) -> None:
    publish_stamp(state_dir / state_files.BROKER_HEARTBEAT, now - seconds_ago)


def test_a_heartbeat_counts_as_fresh_up_to_three_seconds_old_six_of_the_half_second_beats_the_broker_writes(
        tmp_path):
    _stamped(tmp_path, 3.0)
    assert broker_heartbeat.is_fresh(tmp_path, now=1000.0)

    _stamped(tmp_path, 3.1)
    assert not broker_heartbeat.is_fresh(tmp_path, now=1000.0)


def test_a_heartbeat_never_written_or_not_a_number_is_not_fresh(tmp_path):
    assert not broker_heartbeat.is_fresh(tmp_path, now=1000.0)

    (tmp_path / state_files.BROKER_HEARTBEAT).write_text("not a timestamp", encoding="utf-8")
    assert not broker_heartbeat.is_fresh(tmp_path, now=1000.0)


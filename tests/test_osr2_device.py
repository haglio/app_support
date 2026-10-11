from __future__ import annotations

from pathlib import Path

from app_support.file_channel import publish_stamp
from app_support.osr2_device import SILENT_ONCE_OFF_S, switched_on


def _spoke_at(tmp_path: Path, when: float) -> Path:
    stamp = tmp_path / "osr2_serial_rx.txt"
    publish_stamp(stamp, when)
    return stamp


def test_an_osr2_heard_from_within_the_window_is_switched_on(tmp_path):
    assert switched_on(_spoke_at(tmp_path, 100.0), now=100.0 + SILENT_ONCE_OFF_S - 0.1)


def test_one_silent_for_the_whole_window_is_switched_off(tmp_path):
    assert not switched_on(_spoke_at(tmp_path, 100.0), now=100.0 + SILENT_ONCE_OFF_S)


def test_one_never_heard_from_is_switched_off(tmp_path):
    assert not switched_on(tmp_path / "osr2_serial_rx.txt", now=100.0)


def test_a_stamp_that_cannot_be_read_says_switched_off(tmp_path):
    stamp = tmp_path / "osr2_serial_rx.txt"
    stamp.write_text("not a time", encoding="utf-8")

    assert not switched_on(stamp, now=100.0)


def test_the_window_outlasts_the_15_seconds_between_a_powered_osr2s_reports():
    assert 15.0 < SILENT_ONCE_OFF_S <= 20.0

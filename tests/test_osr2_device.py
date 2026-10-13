from __future__ import annotations

from pathlib import Path

from app_support.file_channel import publish_stamp
from app_support.osr2_device import (
    ANSWERING_TRUSTED_S,
    ANSWERS_ONCE_OFF_S,
    SILENT_ONCE_OFF_S,
    switched_on,
)
from app_support.state_files import OSR2_SERIAL_ANSWER, OSR2_SERIAL_RX


def _spoke_at(state_dir: Path, when: float) -> None:
    publish_stamp(state_dir / OSR2_SERIAL_RX, when)


def _answered_at(state_dir: Path, when: float) -> None:
    publish_stamp(state_dir / OSR2_SERIAL_ANSWER, when)


def test_an_osr2_heard_from_within_the_window_is_switched_on(tmp_path):
    _spoke_at(tmp_path, 100.0)

    assert switched_on(tmp_path, now=100.0 + SILENT_ONCE_OFF_S - 0.1)


def test_one_silent_for_the_whole_window_is_switched_off(tmp_path):
    _spoke_at(tmp_path, 100.0)

    assert not switched_on(tmp_path, now=100.0 + SILENT_ONCE_OFF_S)


def test_one_never_heard_from_is_switched_off(tmp_path):
    assert not switched_on(tmp_path, now=100.0)


def test_a_stamp_that_cannot_be_read_says_switched_off(tmp_path):
    (tmp_path / OSR2_SERIAL_RX).write_text("not a time", encoding="utf-8")

    assert not switched_on(tmp_path, now=100.0)


def test_the_window_outlasts_the_15_seconds_between_a_powered_osr2s_reports():
    assert 15.0 < SILENT_ONCE_OFF_S <= 20.0


def test_one_answering_the_brokers_question_is_switched_off_seconds_after_it_stops(tmp_path):
    _spoke_at(tmp_path, 100.0)
    _answered_at(tmp_path, 100.0)

    assert switched_on(tmp_path, now=100.0 + ANSWERS_ONCE_OFF_S - 0.1)
    assert not switched_on(tmp_path, now=100.0 + ANSWERS_ONCE_OFF_S)


def test_one_that_stopped_answering_but_still_talks_is_switched_on(tmp_path):
    _answered_at(tmp_path, 100.0)
    _spoke_at(tmp_path, 100.0 + ANSWERING_TRUSTED_S)

    assert switched_on(tmp_path, now=100.0 + ANSWERING_TRUSTED_S + 0.1)


def test_a_switched_off_osr2_stays_off_as_its_answers_stop_counting(tmp_path):
    _spoke_at(tmp_path, 100.0)
    _answered_at(tmp_path, 100.0)

    assert not switched_on(tmp_path, now=100.0 + ANSWERING_TRUSTED_S + 0.1)


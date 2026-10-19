from __future__ import annotations

from pathlib import Path

from app_support.file_channel import publish_stamp, write_flag
from app_support.osr2_device import (
    ANSWERING_TRUSTED_S,
    ANSWERS_ONCE_OFF_S,
    SILENT_ONCE_OFF_S,
    TROUBLE_RENEWED_WITHIN_S,
    Osr2Mode,
    Osr2Trouble,
    mode,
    switched_on,
    trouble,
)
from app_support.state_files import (
    BROKER_MODE,
    OSR2_NOT_ANSWERING,
    OSR2_NOT_FOUND,
    OSR2_SERIAL_ANSWER,
    OSR2_SERIAL_RX,
)


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


def test_a_switched_off_osr2_is_off_whatever_the_broker_last_said_of_it(tmp_path):
    write_flag(tmp_path / BROKER_MODE, True)

    assert mode(tmp_path, now=100.0) is Osr2Mode.OFF



def test_one_switched_on_in_its_own_auto_mode_is_auto(tmp_path):
    _spoke_at(tmp_path, 100.0)
    write_flag(tmp_path / BROKER_MODE, True)

    assert mode(tmp_path, now=100.5) is Osr2Mode.AUTO


def test_one_switched_on_and_not_in_its_auto_mode_is_controlled(tmp_path):
    _spoke_at(tmp_path, 100.0)
    write_flag(tmp_path / BROKER_MODE, False)

    assert mode(tmp_path, now=100.5) is Osr2Mode.CONTROLLED


def test_one_whose_broker_has_not_said_is_controlled(tmp_path):
    _spoke_at(tmp_path, 100.0)

    assert mode(tmp_path, now=100.5) is Osr2Mode.CONTROLLED


def test_an_osr2_the_broker_cannot_find_is_not_found(tmp_path):
    publish_stamp(tmp_path / OSR2_NOT_FOUND, 100.0)

    assert trouble(tmp_path, now=101.0) is Osr2Trouble.NOT_FOUND


def test_a_not_found_stamp_the_broker_stopped_renewing_is_no_trouble(tmp_path):
    publish_stamp(tmp_path / OSR2_NOT_FOUND, 100.0)

    assert trouble(tmp_path, now=100.0 + TROUBLE_RENEWED_WITHIN_S) is None


def test_an_osr2_driven_for_minutes_without_a_word_back_is_not_answering(tmp_path):
    publish_stamp(tmp_path / OSR2_NOT_ANSWERING, 100.0)

    assert trouble(tmp_path, now=101.0) is Osr2Trouble.NOT_ANSWERING


def test_an_osr2_heard_again_has_no_trouble_though_the_broker_said_so_a_moment_ago(tmp_path):
    publish_stamp(tmp_path / OSR2_NOT_ANSWERING, 100.0)
    _answered_at(tmp_path, 100.5)

    assert trouble(tmp_path, now=100.6) is None


def test_an_osr2_the_broker_lost_is_not_found_whatever_it_said_of_its_answers(tmp_path):
    publish_stamp(tmp_path / OSR2_NOT_ANSWERING, 100.0)
    publish_stamp(tmp_path / OSR2_NOT_FOUND, 100.5)

    assert trouble(tmp_path, now=101.0) is Osr2Trouble.NOT_FOUND

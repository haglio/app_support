from __future__ import annotations

from app_support.osr2_turn_off_reminder import remind_to_turn_off, what_closed
from app_support.state_files import OSR2_TURN_OFF_REMINDER


def test_an_app_closing_leaves_its_name_where_the_broker_takes_it(tmp_path):
    remind_to_turn_off(tmp_path, closed="Example App")

    assert what_closed(tmp_path) == "Example App"


def test_the_broker_takes_each_ask_once(tmp_path):
    remind_to_turn_off(tmp_path, closed="Example App")
    what_closed(tmp_path)

    assert what_closed(tmp_path) is None
    assert not (tmp_path / OSR2_TURN_OFF_REMINDER).exists()


def test_nothing_asked_is_nothing_closed(tmp_path):
    assert what_closed(tmp_path) is None


def test_an_empty_ask_names_no_app(tmp_path):
    (tmp_path / OSR2_TURN_OFF_REMINDER).write_text("  \n", encoding="utf-8")

    assert what_closed(tmp_path) is None

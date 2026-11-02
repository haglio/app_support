from __future__ import annotations

import time
from pathlib import Path

import pytest

from app_support import (
    file_channel,
    loading_screen,
    logging_utils,
    origenerator_handoff,
    peer_watch,
    ports,
    production_update,
    testing,
    win32,
)


def test_a_held_file_is_retried_without_the_wait():
    answers = [PermissionError(13, "held"), "read"]

    def read():
        answer = answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer

    with testing.no_wait_for_a_held_file() as sleep:
        assert file_channel.retried_while_held(read) == "read"
    sleep.assert_called_once()


def test_the_file_channels_clock_is_the_one_the_test_names():
    with testing.file_channel_clock_at(123.45):
        assert file_channel.time.time() == 123.45
    assert file_channel.time is time


def test_that_clock_leaves_every_other_clock_on_the_machine_alone():
    with testing.file_channel_clock_at(123.45):
        assert time.time() != 123.45


@pytest.mark.parametrize("answer", [True, False])
def test_the_stand_down_answer_is_the_one_the_test_names(answer):
    with testing.stood_down(answer):
        assert peer_watch.is_stood_down("example") is answer


def test_the_stand_down_question_can_be_listened_to():
    asked = []
    with testing.stood_down_asking(side_effect=lambda key, **_kw: asked.append(key) or False):
        peer_watch.is_stood_down("example")
    assert asked == ["example"]


def test_a_stand_down_written_or_cleared_leaves_no_marker(tmp_path):
    environ = {"LOCALAPPDATA": str(tmp_path)}
    with testing.stand_down_written() as wrote, testing.stand_down_cleared() as cleared:
        peer_watch.stand_down("example", environ=environ)
        peer_watch.clear_stand_down("example", environ=environ)
    wrote.assert_called_once()
    cleared.assert_called_once()
    assert list(tmp_path.iterdir()) == []


def test_every_mutex_is_free():
    with testing.mutex_free():
        assert win32.try_acquire_mutex("Global\\Example") is not None


def test_no_popup_reaches_the_screen():
    with testing.error_popup() as popup:
        win32.show_error_popup("Title", "Body")
    popup.assert_called_once_with("Title", "Body")


def test_the_taskbar_calls_reach_no_window():
    with testing.app_id_claimed() as claimed, testing.pinned_shortcuts_stamped(return_value={}) as stamped, \
            testing.window_dressed() as dressed, testing.no_taskbar_description():
        win32.set_app_user_model_id("Example")
        assert win32.stamp_pinned_shortcuts("Example", ["Example"]) == {}
        win32.dress_window(1, "Example", None)
        assert win32.described_taskbar_app("Example") is None
    claimed.assert_called_once_with("Example")
    stamped.assert_called_once_with("Example", ["Example"])
    dressed.assert_called_once_with(1, "Example", None)


def test_logging_is_left_as_the_suite_set_it():
    with testing.logging_left_alone() as configured, testing.exception_hooks_left_alone() as hooked:
        logging_utils.configure_logging("example")
        logging_utils.install_exception_logging("example")
    configured.assert_called_once_with("example")
    hooked.assert_called_once_with("example")


def test_a_hand_over_writes_no_takeover(tmp_path):
    with testing.origenerator_handed_over() as handed:
        origenerator_handoff.hand_over(tmp_path, args=[])
    handed.assert_called_once_with(tmp_path, args=[])
    assert list(tmp_path.iterdir()) == []


def test_the_osr2_slot_is_the_port_the_test_names():
    with testing.osr2_slot_at(5):
        assert ports.OSR2_SLOT == 5


def test_the_screens_are_the_ones_the_test_names():
    with testing.screens_measured_as(None):
        assert loading_screen.screens() is None


def test_an_update_waits_for_the_named_checkout_alone_and_at_once():
    checkout = Path("example")
    with testing.update_waiting_for(checkout):
        assert production_update.UP_BEFORE_AN_UPDATE_S == 0.0
        assert production_update.waits_for_programs_to_close(checkout) is True
        assert production_update.waits_for_programs_to_close(Path("other")) is False


def test_starting_again_starts_nothing():
    with testing.start_again_stand_in() as started:
        production_update.start_again_after(1, Path("launcher"))
    started.assert_called_once_with(1, Path("launcher"))

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch


def no_wait_for_a_held_file(**how: Any):
    return patch("app_support.file_channel.time.sleep", **how)


def file_channel_clock_at(now: float):
    return patch("app_support.file_channel.time", SimpleNamespace(time=lambda: now, sleep=lambda _s: None))


def stood_down(answer: bool):
    return patch("app_support.peer_watch.is_stood_down", return_value=answer)


def stood_down_asking(**how: Any):
    return patch("app_support.peer_watch.is_stood_down", **how)


def stand_down_written():
    return patch("app_support.peer_watch.stand_down")


def stand_down_cleared():
    return patch("app_support.peer_watch.clear_stand_down")


def mutex_free():
    return patch("app_support.win32.try_acquire_mutex", return_value=object())


def error_popup(**how: Any):
    return patch("app_support.win32.show_error_popup", **how)


def app_id_claimed(**how: Any):
    return patch("app_support.win32.set_app_user_model_id", **how)


def pinned_shortcuts_stamped(**how: Any):
    return patch("app_support.win32.stamp_pinned_shortcuts", **how)


def window_dressed(**how: Any):
    return patch("app_support.win32.dress_window", **how)


def no_taskbar_description():
    return patch("app_support.win32.described_taskbar_app", return_value=None)


def logging_left_alone():
    return patch("app_support.logging_utils.configure_logging")


def exception_hooks_left_alone():
    return patch("app_support.logging_utils.install_exception_logging")


def origenerator_handed_over(**how: Any):
    return patch("app_support.origenerator_handoff.hand_over", **how)


def osr2_slot_at(port: int):
    return patch("app_support.ports.OSR2_SLOT", port)


def screens_measured_as(screens: Any):
    return patch("app_support.loading_screen.screens", return_value=screens)


def start_again_stand_in(**how: Any):
    return patch("app_support.production_update.start_again_after", **how)


@contextmanager
def update_waiting_for(checkout: Path) -> Iterator[None]:
    with patch("app_support.production_update.UP_BEFORE_AN_UPDATE_S", 0.0), \
            patch("app_support.production_update.waits_for_programs_to_close",
                  side_effect=lambda asked: asked == checkout):
        yield

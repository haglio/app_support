from __future__ import annotations

import struct
import subprocess
from pathlib import Path

import pytest

from app_support import copyable_alert

pytestmark = pytest.mark.timeout(120)


def test_the_window_comes_up_with_its_message_copy_and_ok_though_started_hidden(desktop_of_its_own):
    desktop = desktop_of_its_own
    pid = desktop.start(copyable_alert.COMMAND, hidden=True, environment=copyable_alert.environment(
        "Example App", "The scene file could not be read.", copyable_alert.WARNING))

    shown = desktop.window_titled("Example App")
    desktop.press("Example App", "OK")

    assert "The scene file could not be read." in shown
    assert {"OK", copyable_alert.COPY} <= set(shown)
    assert desktop.ended_within(pid, 30)


def _an_icon(tmp_path: Path) -> Path:
    side = 16
    pixels = bytes([0x40, 0x80, 0xC0, 0xFF]) * side * side
    and_mask = bytes(side * 4)
    image = struct.pack("<LllHHLLllLL", 40, side, side * 2, 1, 32, 0, len(pixels) + len(and_mask), 0, 0, 0, 0)
    image += pixels + and_mask
    path = tmp_path / "example.ico"
    path.write_bytes(struct.pack("<HHH", 0, 1, 1) + struct.pack("<BBBBHHLL", side, side, 0, 0, 1, 32, len(image), 22)
                     + image)
    return path


def test_the_window_given_its_apps_icon_comes_up_wearing_it(desktop_of_its_own, tmp_path):
    desktop = desktop_of_its_own
    pid = desktop.start(copyable_alert.COMMAND, hidden=True, environment=copyable_alert.environment(
        "Example App", "The scene file could not be read.", copyable_alert.ERROR, app_icon=_an_icon(tmp_path)))

    desktop.window_titled("Example App")
    worn = desktop.wears_an_icon("Example App")
    desktop.press("Example App", "OK")

    assert worn
    assert desktop.ended_within(pid, 30)


def test_the_window_without_its_apps_icon_wears_none(desktop_of_its_own):
    desktop = desktop_of_its_own
    pid = desktop.start(copyable_alert.COMMAND, hidden=True, environment=copyable_alert.environment(
        "Example App", "The scene file could not be read.", copyable_alert.ERROR))

    desktop.window_titled("Example App")
    worn = desktop.wears_an_icon("Example App")
    desktop.press("Example App", "OK")

    assert not worn
    assert desktop.ended_within(pid, 30)


def test_the_window_is_told_its_title_message_and_icon_through_its_environment():
    told = copyable_alert.environment("Example App", "Nothing to do.", copyable_alert.INFORMATION,
                                      inherited={"PATH": "C:/example"})

    assert told == {"PATH": "C:/example", copyable_alert.TITLE: "Example App",
                    copyable_alert.MESSAGE: "Nothing to do.", copyable_alert.ICON: "64"}


def test_showing_says_whether_the_window_came_up():
    def ran(code):
        return lambda command, **_how: subprocess.CompletedProcess(command, code)

    assert copyable_alert.show("Example App", "Nothing to do.", run=ran(0)) is True
    assert copyable_alert.show("Example App", "Nothing to do.", run=ran(1)) is False


def test_a_machine_without_powershell_is_told_the_window_did_not_come_up():
    def missing(_command, **_how):
        raise FileNotFoundError

    assert copyable_alert.show("Example App", "Nothing to do.", run=missing) is False


def test_what_is_copied_is_the_title_a_blank_line_and_the_message():
    assert copyable_alert.said("Example App", "Nothing to do.") == "Example App\n\nNothing to do."


def test_a_window_given_its_apps_icon_is_told_the_icon_and_a_taskbar_identity_of_its_own(tmp_path):
    icon = tmp_path / "example.ico"

    told = copyable_alert.environment("Example App", "Nothing to do.", copyable_alert.ERROR, app_icon=icon,
                                      inherited={})

    assert told[copyable_alert.APP_ICON] == str(icon)
    assert told[copyable_alert.APP_ID] == copyable_alert.taskbar_identity(str(icon))


def test_a_taskbar_identity_is_the_same_for_one_app_and_differs_between_apps():
    assert copyable_alert.taskbar_identity("Example App") == copyable_alert.taskbar_identity("Example App")
    assert copyable_alert.taskbar_identity("Example App") != copyable_alert.taskbar_identity("Other App")
    assert len(copyable_alert.taskbar_identity("Example App" * 50)) <= 128

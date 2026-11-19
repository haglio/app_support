from __future__ import annotations

import subprocess

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

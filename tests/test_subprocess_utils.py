"""hidden_subprocess_kwargs: the two settings that keep a console child invisible.

Against the real ``STARTUPINFO`` and the real flag constants, with only the
platform patched, so a wrong constant fails and a refactor of the import does
not.
"""
from __future__ import annotations

import subprocess
from unittest.mock import patch

import pytest

from app_support.subprocess_utils import hidden_subprocess_kwargs

_windows_half = pytest.mark.skipif(
    not hasattr(subprocess, "STARTUPINFO"),
    reason="the Windows half of subprocess is what these check",
)


def _platform(name: str):
    return patch("app_support.subprocess_utils.sys.platform", name)


def test_off_windows_no_creation_flags_are_asked_for():
    with _platform("linux"):
        assert hidden_subprocess_kwargs() == {}


def test_off_windows_the_added_flag_has_nowhere_to_go_either():
    with _platform("linux"):
        assert hidden_subprocess_kwargs(creationflags=8) == {}


@_windows_half
def test_both_suppressions_are_applied_not_just_one():
    # CREATE_NO_WINDOW alone leaves a child that explicitly asks for a window
    # showing one, and SW_HIDE alone still allocates the console; a console
    # flashing over the video is the bug either half on its own permits.
    with _platform("win32"):
        result = hidden_subprocess_kwargs()

    assert set(result) == {"creationflags", "startupinfo"}
    assert result["creationflags"] == subprocess.CREATE_NO_WINDOW
    startupinfo = result["startupinfo"]
    assert isinstance(startupinfo, subprocess.STARTUPINFO)
    assert startupinfo.dwFlags & subprocess.STARTF_USESHOWWINDOW
    assert startupinfo.wShowWindow == subprocess.SW_HIDE


@_windows_half
def test_a_flag_the_caller_adds_rides_with_the_hiding_one():
    # A child that also has to be detached, or run at a lower priority: OR-ed
    # here, so the caller never again spells the console flag by hand and
    # forgets the STARTUPINFO half.
    with _platform("win32"):
        result = hidden_subprocess_kwargs(creationflags=8)

    assert result["creationflags"] == subprocess.CREATE_NO_WINDOW | 8
    assert result["startupinfo"].wShowWindow == subprocess.SW_HIDE

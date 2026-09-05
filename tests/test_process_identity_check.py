"""Tests for the shared naming check.

Eight repos will hand this the call at the top of their entry point and believe
the answer, so most of what is here proves the check still goes red: for an app
that names nothing, names the wrong thing, copies the wrong launcher, leaves its
mark off, or falls over when there is nothing to copy.  Every app name is
invented; the one real thing is the interpreter this suite runs under, copied
somewhere disposable.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from test_process_identity import _icon

from app_support.process_identity import ProcessNamer
from app_support.process_identity_check import assert_the_app_names_its_process


def _an_app_that_names_itself(icon: Path | None = None, interpreter: str = "python.exe"):
    """What every entry point in the family does, as a Highdeas would."""
    return lambda: ProcessNamer("Highdeas", icon=icon).name_this_process(
        "Highdeas", interpreter=interpreter)


class TestAnAppThatNamesItself:
    def test_passes_for_a_console_launcher_with_a_mark(self, tmp_path: Path):
        icon = _icon(tmp_path)

        assert_the_app_names_its_process(
            _an_app_that_names_itself(icon, "python.exe"), tmp_path / "run",
            app_name="Highdeas", role="Highdeas", interpreter="python.exe",
            row="Highdeas", icon=icon)

    def test_passes_for_a_windowed_launcher_and_no_mark(self, tmp_path: Path):
        assert_the_app_names_its_process(
            _an_app_that_names_itself(interpreter="pythonw.exe"), tmp_path,
            app_name="Highdeas", role="Highdeas", interpreter="pythonw.exe")

    def test_passes_for_one_process_of_several(self, tmp_path: Path):
        def names_its_tray():
            ProcessNamer("Broker").name_this_process("Tray")

        assert_the_app_names_its_process(
            names_its_tray, tmp_path, app_name="Broker", role="Tray", row="Broker – Tray")


class TestWhatItRefuses:
    def test_an_app_that_names_nothing(self, tmp_path: Path):
        with pytest.raises(AssertionError, match=r"Highdeas-Highdeas\.exe and nothing else"):
            assert_the_app_names_its_process(
                lambda: None, tmp_path, app_name="Highdeas", role="Highdeas")

    def test_a_copy_named_for_the_wrong_role(self, tmp_path: Path):
        with pytest.raises(AssertionError, match=r"Highdeas-Editor\.exe"):
            assert_the_app_names_its_process(
                _an_app_that_names_itself(), tmp_path,
                app_name="Highdeas", role="Editor", interpreter="python.exe")

    def test_a_copy_made_from_the_other_launcher(self, tmp_path: Path):
        # The check says the .vbs runs python.exe; the app copied pythonw.
        with pytest.raises(AssertionError, match=r"not made from python\.exe"):
            assert_the_app_names_its_process(
                _an_app_that_names_itself(interpreter="pythonw.exe"), tmp_path,
                app_name="Highdeas", role="Highdeas", interpreter="python.exe")

    def test_an_app_that_copies_whatever_it_is_running_under(self, tmp_path: Path):
        """Naming a copy after a copy, on every run after the first.  The check
        runs the app under the other launcher, so this also copies the wrong
        kind of image, which is what it reads back."""
        def copies_itself():
            ProcessNamer("Highdeas").named_exe(sys.executable, "Highdeas")

        with pytest.raises(AssertionError, match=r"not made from python\.exe"):
            assert_the_app_names_its_process(
                copies_itself, tmp_path, app_name="Highdeas", role="Highdeas",
                interpreter="python.exe")

    def test_a_row_that_reads_wrong(self, tmp_path: Path):
        with pytest.raises(AssertionError, match="the row would read 'Highdeas'"):
            assert_the_app_names_its_process(
                _an_app_that_names_itself(), tmp_path, app_name="Highdeas",
                role="Highdeas", interpreter="python.exe", row="Highdeas – Highdeas")

    def test_a_copy_without_the_apps_mark(self, tmp_path: Path):
        with pytest.raises(AssertionError, match=r"does not carry app\.ico"):
            assert_the_app_names_its_process(
                _an_app_that_names_itself(), tmp_path / "run", app_name="Highdeas",
                role="Highdeas", interpreter="python.exe", icon=_icon(tmp_path))

    def test_an_app_that_falls_over_with_nothing_to_copy(self, tmp_path: Path):
        """The old shape, minus its try/except: the path is derived outside
        anything that guards it, so an empty sys.executable is a ValueError at
        the top of main()."""
        def names_itself_unguarded():
            ProcessNamer("Highdeas").named_exe(
                Path(sys.executable).with_name("python.exe"), "Highdeas")

        with pytest.raises(AssertionError, match="would take the launch down"):
            assert_the_app_names_its_process(
                names_itself_unguarded, tmp_path, app_name="Highdeas", role="Highdeas",
                interpreter="python.exe")

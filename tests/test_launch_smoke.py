"""Tests for the shared launch-smoke helper.

Seven repos will hand this their launcher's entry points and believe the answer.
A walk that quietly stopped finding imports would leave all seven suites green
and all seven icons able to do nothing, so most of what is here exists to prove
the helper still goes red: that it finds the imports buried in a ``main()``, and
that each assertion it provides fails when the thing it checks is not true.

Every module name here is invented and the packages are built in a temp
directory, because a fixture pointing at a real repo would test that repo rather
than this walk.
"""
from __future__ import annotations

import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from app_support.launch_smoke import (
    assert_an_unresolvable_import_is_caught,
    assert_every_import_resolves,
    assert_the_walk_reached,
    launch_imports,
)


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(text), encoding="utf-8")
    return path


def _one_file(tmp_path: Path, text: str) -> list[str]:
    """The statements the walk reads out of a single launch file."""
    return launch_imports("pkg", [_write(tmp_path / "pkg" / "app.py", text)])


class TestWhatTheWalkFinds:
    def test_finds_a_module_level_import(self, tmp_path: Path):
        assert _one_file(tmp_path, "import json\n") == ["import json"]

    def test_finds_an_import_buried_inside_a_function(self, tmp_path: Path):
        """The whole reason the statements come off the AST rather than off a
        list: an import inside ``main()`` never runs under a test that imports
        the module and stops at the top of it.
        """
        got = _one_file(tmp_path, """
            def main():
                from pkg.window import Window
                return Window
        """)
        assert got == ["from pkg.window import Window"]

    def test_keeps_the_symbols_a_from_import_names(self, tmp_path: Path):
        """Replayed whole, so a symbol the launch names but the module no longer
        defines fails here too -- a rename is the same dead icon as a syntax
        error.
        """
        got = _one_file(tmp_path, "from pkg.state import Store, load as read\n")
        assert got == ["from pkg.state import Store, load as read"]

    def test_renders_a_relative_import_absolute(self, tmp_path: Path):
        got = _one_file(tmp_path, "from . import state\nfrom .window import Window\n")
        assert got == ["from pkg import state", "from pkg.window import Window"]

    def test_reads_every_launch_file_it_is_given(self, tmp_path: Path):
        entry = _write(tmp_path / "pkg" / "__main__.py", "from pkg.app import main\n")
        app = _write(tmp_path / "pkg" / "app.py", "import json\n")
        assert launch_imports("pkg", [entry, app]) == [
            "from pkg.app import main", "import json"]


class TestWhatTheWalkLeavesOut:
    def test_skips_a_type_checking_body(self, tmp_path: Path):
        """Never executed, at launch or anywhere."""
        got = _one_file(tmp_path, """
            from typing import TYPE_CHECKING
            if TYPE_CHECKING:
                from pkg.heavy import Thing
        """)
        assert got == ["from typing import TYPE_CHECKING"]

    def test_skips_a_type_checking_body_written_through_the_module(self, tmp_path: Path):
        """`if typing.TYPE_CHECKING:` is the same statement spelled the other
        way, and a launcher that writes it that way must not have those imports
        insisted on -- it would be a red smoke test for an app that launches.
        """
        got = _one_file(tmp_path, """
            import typing
            if typing.TYPE_CHECKING:
                from pkg.heavy import Thing
        """)
        assert got == ["import typing"]

    def test_skips_an_import_the_module_already_tolerates_missing(self, tmp_path: Path):
        """The launch survives it, so insisting on it would fail a run that the
        real launcher would have completed.
        """
        got = _one_file(tmp_path, """
            try:
                from pkg.optional import Extra
            except ImportError:
                Extra = None
        """)
        assert got == []

    def test_a_tolerated_import_still_counts_when_caught_among_others(self, tmp_path: Path):
        """`except (ImportError, OSError):` tolerates the missing module just as
        squarely as the single-name form. Reading only the single form would
        replay an import the launch already survives, and fail a launcher that
        works.
        """
        got = _one_file(tmp_path, """
            try:
                from pkg.optional import Extra
            except (OSError, ImportError):
                Extra = None
        """)
        assert got == []

    def test_a_bare_except_does_not_make_an_import_optional(self, tmp_path: Path):
        """A broad ``except`` around a launch body is an error *reporter* -- it
        puts a dialog on screen or writes a crash log -- so an import inside it
        is required, not optional: it failing is exactly the launch failure this
        exists to catch.
        """
        got = _one_file(tmp_path, """
            try:
                from pkg.window import Window
            except:  # noqa: E722
                Window = None
        """)
        assert got == ["from pkg.window import Window"]

    def test_skips_the_compiler_directive(self, tmp_path: Path):
        """``from __future__ import`` loads no module, and is legal only at the
        top of a file -- replayed among the others it is a SyntaxError rather
        than a check of anything.
        """
        got = _one_file(tmp_path, "from __future__ import annotations\nimport json\n")
        assert got == ["import json"]


class TestAgainstARealInterpreter:
    """The replay itself, driven the way a repo's own runner will drive it."""

    def _package(self, tmp_path: Path, *, app_body: str) -> Path:
        _write(tmp_path / "pkg" / "__init__.py", "")
        _write(tmp_path / "pkg" / "window.py", "class Window:\n    pass\n")
        _write(tmp_path / "pkg" / "__main__.py", "from pkg.app import main\n")
        _write(tmp_path / "pkg" / "app.py", app_body)
        return tmp_path

    def _run(self, root: Path):
        def run(statements: list[str]) -> subprocess.CompletedProcess:
            env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
            return subprocess.run(
                [sys.executable, "-c", "\n".join(statements)],
                cwd=root, env=env, capture_output=True, text=True,
            )
        return run

    def _files(self, root: Path) -> list[Path]:
        return [root / "pkg" / "__main__.py", root / "pkg" / "app.py"]

    def test_a_launch_whose_imports_all_resolve_passes(self, tmp_path: Path):
        root = self._package(tmp_path, app_body="""
            def main():
                from pkg.window import Window
                return Window
        """)
        assert_every_import_resolves(
            self._run(root), launch_imports("pkg", self._files(root)))

    def test_a_launch_naming_a_symbol_that_is_gone_fails(self, tmp_path: Path):
        """The failure this whole harness exists for, end to end: the module is
        importable, the symbol is not, and a module-level import test would
        never have noticed.
        """
        root = self._package(tmp_path, app_body="""
            def main():
                from pkg.window import NoLongerHere
                return NoLongerHere
        """)
        with pytest.raises(AssertionError):
            assert_every_import_resolves(
                self._run(root), launch_imports("pkg", self._files(root)))

    def test_the_negative_control_catches_an_unresolvable_import(self, tmp_path: Path):
        root = self._package(tmp_path, app_body="""
            def main():
                from pkg.window import Window
                return Window
        """)
        assert_an_unresolvable_import_is_caught(
            self._run(root), launch_imports("pkg", self._files(root)), "pkg.window")


class TestTheAssertionsGoRed:
    """A helper that stopped working must fail, never pass quietly.

    These are the cases that keep the other repos' guards honest: each provided
    assertion is handed the situation it exists to reject, and has to reject it.
    """

    def _reports(self, returncode: int, stderr: str = ""):
        def run(statements: list[str]) -> subprocess.CompletedProcess:
            return subprocess.CompletedProcess(
                args=statements, returncode=returncode, stdout="", stderr=stderr)
        return run

    def test_a_failing_replay_fails_the_assertion(self):
        with pytest.raises(AssertionError):
            assert_every_import_resolves(
                self._reports(1, "ModuleNotFoundError: no such thing"), ["import json"])

    def test_the_failing_replays_own_output_is_what_gets_reported(self):
        with pytest.raises(AssertionError, match="no such thing"):
            assert_every_import_resolves(
                self._reports(1, "ModuleNotFoundError: no such thing"), ["import json"])

    def test_a_walk_that_found_nothing_fails_rather_than_passing_vacuously(self):
        """The disarm this helper could cause across eight repos at once: a walk
        that silently returns nothing satisfies every "does it import cleanly?"
        check trivially, because there is nothing left to import.
        """
        with pytest.raises(AssertionError):
            assert_the_walk_reached([], ["pkg.state"])

    def test_a_walk_that_missed_one_named_module_fails(self):
        with pytest.raises(AssertionError):
            assert_the_walk_reached(["import json"], ["pkg.state"])

    def test_a_walk_that_reached_every_named_module_passes(self):
        assert_the_walk_reached(
            ["from pkg.state import Store", "import json"], ["pkg.state"])

    def test_a_negative_control_that_reported_success_fails_the_assertion(self):
        """If the replay reported success even with a symbol that cannot exist,
        every assertion built on it would pass for the same empty reason.

        The stderr says the right thing, so only the exit code can be what
        rejects this -- otherwise the case is killed by the other assertion and
        the one it is written for goes unpinned.
        """
        with pytest.raises(AssertionError):
            assert_an_unresolvable_import_is_caught(
                self._reports(0, "NoSuchSymbol"), ["import json"], "pkg.window")

    def test_a_negative_control_failing_for_some_other_reason_fails(self):
        """Non-zero is not enough: the replay has to fail *on the symbol that
        was planted*, or the control is only proving the subprocess is broken.
        """
        with pytest.raises(AssertionError):
            assert_an_unresolvable_import_is_caught(
                self._reports(1, "PermissionError: something else entirely"),
                ["import json"], "pkg.window")

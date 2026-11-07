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
    return launch_imports("pkg", [_write(tmp_path / "pkg" / "app.py", text)])


class TestWhatTheWalkFinds:
    def test_finds_a_module_level_import(self, tmp_path: Path):
        assert _one_file(tmp_path, "import json\n") == ["import json"]

    def test_finds_an_import_buried_inside_a_function(self, tmp_path: Path):
        got = _one_file(tmp_path, """
            def main():
                from pkg.window import Window
                return Window
        """)
        assert got == ["from pkg.window import Window"]

    def test_keeps_the_symbols_a_from_import_names(self, tmp_path: Path):
        got = _one_file(tmp_path, "from pkg.state import Store, load as read\n")
        assert got == ["from pkg.state import Store, load as read"]

    def test_renders_a_relative_import_absolute(self, tmp_path: Path):
        got = _one_file(tmp_path, "from . import state\nfrom .window import Window\n")
        assert got == ["from pkg import state", "from pkg.window import Window"]

    def test_a_launch_file_at_the_top_of_its_package_never_imports_from_deeper_than_one_level(self, tmp_path: Path):
        with pytest.raises(AssertionError, match="top of pkg"):
            _one_file(tmp_path, "from ..deeper import thing\n")

    def test_reads_every_launch_file_it_is_given(self, tmp_path: Path):
        entry = _write(tmp_path / "pkg" / "__main__.py", "from pkg.app import main\n")
        app = _write(tmp_path / "pkg" / "app.py", "import json\n")
        assert launch_imports("pkg", [entry, app]) == [
            "from pkg.app import main", "import json"]


class TestWhatTheWalkLeavesOut:
    def test_skips_a_type_checking_body(self, tmp_path: Path):
        got = _one_file(tmp_path, """
            from typing import TYPE_CHECKING
            if TYPE_CHECKING:
                from pkg.heavy import Thing
        """)
        assert got == ["from typing import TYPE_CHECKING"]

    def test_skips_a_type_checking_body_written_through_the_module(self, tmp_path: Path):
        got = _one_file(tmp_path, """
            import typing
            if typing.TYPE_CHECKING:
                from pkg.heavy import Thing
        """)
        assert got == ["import typing"]

    def test_skips_an_import_the_module_already_tolerates_missing(self, tmp_path: Path):
        got = _one_file(tmp_path, """
            try:
                from pkg.optional import Extra
            except ImportError:
                Extra = None
        """)
        assert got == []

    def test_a_tolerated_import_still_counts_when_caught_among_others(self, tmp_path: Path):
        got = _one_file(tmp_path, """
            try:
                from pkg.optional import Extra
            except (OSError, ImportError):
                Extra = None
        """)
        assert got == []

    def test_an_import_inside_a_crash_reporters_except_exception_is_still_required(self, tmp_path: Path):
        got = _one_file(tmp_path, """
            try:
                from pkg.window import Window
            except Exception:
                report_the_crash()
        """)
        assert got == ["from pkg.window import Window"]

    def test_a_bare_except_does_not_make_an_import_optional(self, tmp_path: Path):
        got = _one_file(tmp_path, """
            try:
                from pkg.window import Window
            except:  # noqa: E722
                Window = None
        """)
        assert got == ["from pkg.window import Window"]

    def test_skips_the_compiler_directive(self, tmp_path: Path):
        got = _one_file(tmp_path, "from __future__ import annotations\nimport json\n")
        assert got == ["import json"]


class TestAgainstARealInterpreter:
    def _a_made_up_package_so_the_walk_is_tested_not_a_repo(self, tmp_path: Path, *, app_body: str) -> Path:
        _write(tmp_path / "pkg" / "__init__.py", "")
        _write(tmp_path / "pkg" / "window.py", "class Window:\n    pass\n")
        _write(tmp_path / "pkg" / "__main__.py", "from pkg.app import main\n")
        _write(tmp_path / "pkg" / "app.py", app_body)
        return tmp_path

    def _run_the_launchs_way_without_pytests_path(self, root: Path):
        def run(statements: list[str]) -> subprocess.CompletedProcess:
            env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
            return subprocess.run(
                [sys.executable, "-c", "\n".join(statements)],
                cwd=root, env=env, capture_output=True, text=True, check=False,
            )
        return run

    def _files(self, root: Path) -> list[Path]:
        return [root / "pkg" / "__main__.py", root / "pkg" / "app.py"]

    def test_a_launch_whose_imports_all_resolve_passes(self, tmp_path: Path):
        root = self._a_made_up_package_so_the_walk_is_tested_not_a_repo(tmp_path, app_body="""
            def main():
                from pkg.window import Window
                return Window
        """)
        assert_every_import_resolves(
            self._run_the_launchs_way_without_pytests_path(root), launch_imports("pkg", self._files(root)))

    def test_a_symbol_the_launch_names_and_the_module_lost_fails_here_not_silently_at_the_icon(self, tmp_path: Path):
        root = self._a_made_up_package_so_the_walk_is_tested_not_a_repo(tmp_path, app_body="""
            def main():
                from pkg.window import NoLongerHere
                return NoLongerHere
        """)
        with pytest.raises(AssertionError):
            assert_every_import_resolves(
                self._run_the_launchs_way_without_pytests_path(root), launch_imports("pkg", self._files(root)))

    def test_the_negative_control_catches_an_unresolvable_import(self, tmp_path: Path):
        root = self._a_made_up_package_so_the_walk_is_tested_not_a_repo(tmp_path, app_body="""
            def main():
                from pkg.window import Window
                return Window
        """)
        assert_an_unresolvable_import_is_caught(
            self._run_the_launchs_way_without_pytests_path(root), launch_imports("pkg", self._files(root)),
            "pkg.window")


class TestTheAssertionsGoRed:
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
        with pytest.raises(AssertionError):
            assert_the_walk_reached([], ["pkg.state"])

    def test_a_walk_that_missed_one_named_module_fails(self):
        with pytest.raises(AssertionError):
            assert_the_walk_reached(["import json"], ["pkg.state"])

    def test_a_walk_that_reached_every_named_module_passes(self):
        assert_the_walk_reached(
            ["from pkg.state import Store", "import json"], ["pkg.state"])

    def test_only_the_negative_control_catches_a_replay_that_reports_success_regardless(self):
        succeeds_regardless_yet_names_the_symbol = self._reports(0, "NoSuchSymbol")
        assert_every_import_resolves(succeeds_regardless_yet_names_the_symbol, ["import json"])

        with pytest.raises(AssertionError):
            assert_an_unresolvable_import_is_caught(
                succeeds_regardless_yet_names_the_symbol, ["import json"], "pkg.window")

    def test_a_negative_control_failing_for_some_other_reason_fails(self):
        with pytest.raises(AssertionError):
            assert_an_unresolvable_import_is_caught(
                self._reports(1, "PermissionError: something else entirely"),
                ["import json"], "pkg.window")

"""The family's coverage settings and floor, `app_support.coverage_gate`."""
from __future__ import annotations

import configparser
from pathlib import Path

import pytest

from app_support import coverage_gate


def _read(text: str) -> configparser.ConfigParser:
    parsed = configparser.ConfigParser()
    parsed.read_string(text)
    return parsed


def test_what_is_measured_is_the_repo_itself_less_its_tests():
    """A list of package names drops a root module silently -- coverage takes a
    package or a directory, and an entry point beside them is neither."""
    config = _read(coverage_gate.render_config((), 54.3))
    assert config["run"]["source"].split() == ["."]
    assert "tests/*" in config["run"]["omit"].split()
    assert config["report"]["fail_under"] == "54.3"


def test_the_family_settings_are_the_same_in_every_repo():
    config = _read(coverage_gate.render_config())
    assert config["run"]["relative_files"] == "true"
    assert config["report"]["precision"] == "2"
    excluded = config["report"]["exclude_also"].split("\n")
    assert "if TYPE_CHECKING:" in excluded
    assert 'if __name__ == "__main__":' in excluded


def test_what_a_repo_does_not_unit_test_is_omitted_with_its_reason():
    shell = coverage_gate.NotUnitTested("vr/player.py", "needs a headset and a GL context")
    rendered = coverage_gate.render_config((shell,), 12.0)
    assert "# needs a headset and a GL context\n    vr/player.py" in rendered
    assert "vr/player.py" in _read(rendered)["run"]["omit"].split()


def _repo(root: Path, not_unit_tested=(), floor=40.0) -> Path:
    package = root / "pkg"
    package.mkdir(parents=True, exist_ok=True)
    (package / "__init__.py").write_text("", encoding="utf-8")
    for shell in not_unit_tested:
        shell_file = root / shell.path
        shell_file.parent.mkdir(parents=True, exist_ok=True)
        shell_file.write_text("", encoding="utf-8")
    written = root / ".coveragerc"
    written.write_text(coverage_gate.render_config(not_unit_tested, floor), encoding="utf-8")
    return written


def test_a_repos_floor_survives_the_round_trip(tmp_path):
    written = _repo(tmp_path, floor=76.5)
    assert coverage_gate.floor_of(written) == 76.5
    coverage_gate.assert_config_is_the_familys(written)


def test_a_config_that_drifted_anywhere_but_its_floor_is_refused(tmp_path):
    written = _repo(tmp_path)
    written.write_text(written.read_text(encoding="utf-8").replace("precision = 2", "precision = 0"),
                       encoding="utf-8")
    with pytest.raises(AssertionError, match="precision"):
        coverage_gate.assert_config_is_the_familys(written)


def test_an_excuse_for_a_file_that_has_gone_is_refused(tmp_path):
    """An omit for a file nobody has any more stops excluding anything, and its reason
    outlives the code it was about -- which is how a repo comes to excuse a shell it
    has since split into tested pieces."""
    shell = coverage_gate.NotUnitTested("pkg/shell.py", "needs a headset")
    written = _repo(tmp_path, not_unit_tested=(shell,))
    (tmp_path / "pkg" / "shell.py").unlink()
    with pytest.raises(AssertionError, match=r"pkg/shell\.py"):
        coverage_gate.assert_config_is_the_familys(written, (shell,))


class TestTheFloorAWholeRunEarns:
    def test_a_total_within_a_point_of_the_floor_leaves_it_where_it_is(self):
        assert coverage_gate.risen_floor(95.99, 95.0) is None

    def test_a_total_exactly_a_point_over_the_floor_earns_half_a_point_under_itself(self):
        assert coverage_gate.risen_floor(96.0, 95.0) == 95.5

    def test_the_floor_earned_is_cut_down_to_tenths(self):
        assert coverage_gate.risen_floor(96.47, 95.0) == 95.9

    def test_a_total_a_hair_under_its_tenth_in_floating_point_still_counts_that_tenth(self):
        assert coverage_gate.risen_floor(96.29999999999999, 95.0) == 95.8

    def test_a_floor_raised_from_one_run_holds_the_next_run_that_measures_a_little_less(self):
        """The same code measured 94.75% here in one whole run and 94.48% in the
        next: what a test reaches can depend on how long the machine took."""
        assert coverage_gate.risen_floor(94.75, 91.0) <= 94.48


class TestThePragmasARepoCarries:
    def test_a_line_excused_where_it_stands_is_refused_and_named(self, tmp_path):
        """What a repo does not unit-test is one list with its reasons, in the
        config, never a pragma scattered through the tree where no one counts
        them."""
        written = _repo(tmp_path)
        (tmp_path / "pkg" / "shell.py").write_text(
            "def shown():  # pragma: no cover\n    return 1\n", encoding="utf-8")

        with pytest.raises(AssertionError, match=r"pkg/shell\.py:1"):
            coverage_gate.assert_config_is_the_familys(written)

    def test_a_repo_still_carrying_some_passes_while_it_stays_under_its_ceiling(self, tmp_path):
        written = _repo(tmp_path)
        (tmp_path / "pkg" / "shell.py").write_text(
            "def shown():  # pragma: no cover\n    return 1\n", encoding="utf-8")

        coverage_gate.assert_config_is_the_familys(written, max_pragmas=1)

    def test_what_the_config_leaves_unmeasured_is_not_counted(self, tmp_path):
        """A pragma in a file coverage never measures excuses nothing: the tests,
        and a shell the repo names with its reason."""
        shell = coverage_gate.NotUnitTested("pkg/shell.py", "needs a headset")
        written = _repo(tmp_path, not_unit_tested=(shell,))
        (tmp_path / "pkg" / "shell.py").write_text("x = 1  # pragma: no cover\n", encoding="utf-8")
        (tmp_path / "tests").mkdir()
        (tmp_path / "tests" / "test_pkg.py").write_text("y = 2  # pragma: no cover\n", encoding="utf-8")

        coverage_gate.assert_config_is_the_familys(written, (shell,))

    def test_nothing_under_a_dot_directory_is_counted(self, tmp_path):
        """Coverage walks past them, and they hold whole trees of somebody
        else's code: the venv, and every agent's worktree under `.claude`."""
        written = _repo(tmp_path)
        for under in (".venv/Lib/site-packages/lib.py", ".claude/worktrees/one/pkg/mod.py"):
            (tmp_path / under).parent.mkdir(parents=True)
            (tmp_path / under).write_text("z = 3  # pragma: no cover\n", encoding="utf-8")

        coverage_gate.assert_config_is_the_familys(written)

    def test_nothing_in_a_python_environment_is_counted_wherever_it_sits(self, tmp_path):
        """A repo's tool can install one in a plain folder, as Fun Time's flake gate
        does under `state`: coverage takes a folder holding a `pyvenv.cfg` for
        somebody else's code, and its pip carries pragmas this repo never wrote."""
        written = _repo(tmp_path)
        environment = tmp_path / "state" / "tool_venv"
        library = environment / "Lib" / "site-packages" / "lib.py"
        library.parent.mkdir(parents=True)
        (environment / "pyvenv.cfg").write_text("home = nowhere\n", encoding="utf-8")
        library.write_text("z = 3  # pragma: no cover\n", encoding="utf-8")

        coverage_gate.assert_config_is_the_familys(written)

    def test_a_pragma_beside_a_python_environment_is_still_counted(self, tmp_path):
        written = _repo(tmp_path)
        (tmp_path / "state" / "tool_venv").mkdir(parents=True)
        (tmp_path / "state" / "tool_venv" / "pyvenv.cfg").write_text("home = nowhere\n", encoding="utf-8")
        (tmp_path / "state" / "own.py").write_text("z = 3  # pragma: no cover\n", encoding="utf-8")

        with pytest.raises(AssertionError, match=r"state/own\.py:1"):
            coverage_gate.assert_config_is_the_familys(written)

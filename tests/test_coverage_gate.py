"""The family's coverage floor, `app_support.coverage_gate`."""
from __future__ import annotations

import configparser
from pathlib import Path

import pytest

from app_support import coverage_gate


def _read(text: str) -> configparser.ConfigParser:
    parsed = configparser.ConfigParser()
    parsed.read_string(text)
    return parsed


def test_the_rendered_config_measures_the_shipped_packages_and_nothing_else():
    config = _read(coverage_gate.render_config(("scripture",), (), 54.3))
    assert config["run"]["source"].split() == ["scripture"]
    assert config["report"]["fail_under"] == "54.3"


def test_the_family_settings_are_the_same_in_every_repo():
    config = _read(coverage_gate.render_config(("pkg",), (), 0.0))
    assert config["run"]["relative_files"] == "true"
    assert config["report"]["precision"] == "2"
    excluded = config["report"]["exclude_also"].split("\n")
    assert "if TYPE_CHECKING:" in excluded
    assert 'if __name__ == "__main__":' in excluded


def test_what_a_repo_does_not_unit_test_is_omitted_with_its_reason():
    shell = coverage_gate.NotUnitTested("vr/player.py", "needs a headset and a GL context")
    rendered = coverage_gate.render_config(("vr",), (shell,), 12.0)
    assert "# needs a headset and a GL context\n    vr/player.py" in rendered
    assert _read(rendered)["run"]["omit"].split() == ["vr/player.py"]


def _repo(root: Path, shipped=("pkg",), not_unit_tested=(), floor=40.0) -> Path:
    for name in shipped:
        package = root / name
        package.mkdir(parents=True, exist_ok=True)
        (package / "__init__.py").write_text("", encoding="utf-8")
    for shell in not_unit_tested:
        shell_file = root / shell.path
        shell_file.parent.mkdir(parents=True, exist_ok=True)
        shell_file.write_text("", encoding="utf-8")
    written = root / ".coveragerc"
    written.write_text(coverage_gate.render_config(shipped, not_unit_tested, floor), encoding="utf-8")
    return written


def test_a_repos_floor_survives_the_round_trip(tmp_path):
    written = _repo(tmp_path, floor=76.5)
    assert coverage_gate.floor_of(written) == 76.5
    coverage_gate.assert_config_is_the_familys(written, ("pkg",))


def test_a_config_that_drifted_anywhere_but_its_floor_is_refused(tmp_path):
    written = _repo(tmp_path)
    written.write_text(written.read_text(encoding="utf-8").replace("precision = 2", "precision = 0"),
                       encoding="utf-8")
    with pytest.raises(AssertionError, match="precision"):
        coverage_gate.assert_config_is_the_familys(written, ("pkg",))


def test_a_package_the_repo_no_longer_ships_is_refused(tmp_path):
    written = _repo(tmp_path, shipped=("pkg", "gone"))
    (tmp_path / "gone" / "__init__.py").unlink()
    (tmp_path / "gone").rmdir()
    with pytest.raises(AssertionError, match="gone"):
        coverage_gate.assert_config_is_the_familys(written, ("pkg", "gone"))


def test_an_excuse_for_a_file_that_has_gone_is_refused(tmp_path):
    """An omit for a file nobody has any more stops excluding anything, and its reason
    outlives the code it was about -- which is how a repo comes to excuse a shell it
    has since split into tested pieces."""
    shell = coverage_gate.NotUnitTested("pkg/shell.py", "needs a headset")
    written = _repo(tmp_path, not_unit_tested=(shell,))
    (tmp_path / "pkg" / "shell.py").unlink()
    with pytest.raises(AssertionError, match=r"pkg/shell\.py"):
        coverage_gate.assert_config_is_the_familys(written, ("pkg",), (shell,))

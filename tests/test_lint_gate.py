"""The family's ruff config and lint gate, `app_support.lint`."""
from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

from app_support import lint


def test_the_rendered_config_carries_the_familys_numbers():
    config = tomllib.loads(lint.render_config())
    assert config["line-length"] == 100
    assert config["format"]["quote-style"] == "double"
    assert {"F", "E", "W", "I", "UP", "B", "PL", "PT", "RUF"} <= set(config["lint"]["select"])
    assert config["lint"]["ignore"] == ["E501", "BLE001", "S110"]


def test_a_repos_ratchet_survives_the_round_trip(tmp_path):
    written = tmp_path / "ruff.toml"
    written.write_text(lint.render_config(["PLR2004", "PLC0415"]), encoding="utf-8")
    assert lint.ratchet_of(written) == ("PLR2004", "PLC0415")
    lint.assert_config_is_the_familys(written)  # its own rendering is the family's


def test_a_config_that_drifted_anywhere_but_its_ratchet_is_refused(tmp_path):
    drifted = tmp_path / "ruff.toml"
    drifted.write_text(lint.render_config(["PLR2004"]).replace("line-length = 100", "line-length = 120"),
                       encoding="utf-8")
    with pytest.raises(AssertionError, match="line-length"):
        lint.assert_config_is_the_familys(drifted)


def _repo(tmp_path, source: str) -> Path:
    tmp_path.mkdir(exist_ok=True)
    (tmp_path / "ruff.toml").write_text(lint.render_config(), encoding="utf-8")
    package = tmp_path / "pkg"
    package.mkdir()
    (package / "__init__.py").write_text("", encoding="utf-8")
    (package / "mod.py").write_text(source, encoding="utf-8")
    return tmp_path


def test_a_clean_tree_passes_and_an_unused_import_is_named(tmp_path):
    lint.assert_lint_is_clean(_repo(tmp_path, "def f():\n    return 1\n"))
    dirty = _repo(tmp_path / "dirty", "import os\n\n\ndef f():\n    return 1\n")
    with pytest.raises(AssertionError, match=r"mod\.py:1:8: F401"):
        lint.assert_lint_is_clean(dirty)


def test_another_ruff_than_the_familys_is_not_an_answer(tmp_path, monkeypatch):
    monkeypatch.setattr(lint, "ruff_version", lambda root: "0.1.0")
    with pytest.raises(lint.LintDidNotRun, match=r"0\.1\.0"):
        lint.assert_lint_is_clean(_repo(tmp_path, "x = 1\n"))


def test_a_tree_ruff_never_looked_at_is_not_clean(tmp_path):
    repo = _repo(tmp_path, "x = 1\n")
    (repo / "empty").mkdir()
    lint.assert_lint_is_clean(repo, repo / "pkg")
    with pytest.raises(lint.LintDidNotRun, match="nothing under"):
        lint.assert_lint_is_clean(repo, repo / "empty")

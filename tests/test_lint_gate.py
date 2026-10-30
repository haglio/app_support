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


def test_a_counted_ratchet_keeps_each_rules_places_through_the_round_trip(tmp_path):
    written = tmp_path / "ruff.toml"
    written.write_text(lint.render_config({"PLR2004": 12, "PT018": 3}), encoding="utf-8")
    assert lint.ratchet_of(written) == {"PLR2004": 12, "PT018": 3}
    lint.assert_config_is_the_familys(written)


def test_an_empty_counted_ratchet_keeps_the_exemptions_through_the_round_trip(tmp_path):
    written = tmp_path / "ruff.toml"
    written.write_text(lint.render_config({}), encoding="utf-8")
    assert lint.ratchet_of(written) == {}
    lint.assert_config_is_the_familys(written)


def test_a_config_that_drifted_anywhere_but_its_ratchet_is_refused(tmp_path):
    drifted = tmp_path / "ruff.toml"
    drifted.write_text(lint.render_config(["PLR2004"]).replace("line-length = 100", "line-length = 120"),
                       encoding="utf-8")
    with pytest.raises(AssertionError, match="line-length"):
        lint.assert_config_is_the_familys(drifted)


def _repo(tmp_path, source: str, ratchet=()) -> Path:
    tmp_path.mkdir(exist_ok=True)
    (tmp_path / "ruff.toml").write_text(lint.render_config(ratchet), encoding="utf-8")
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


def test_whitelist_names_and_test_literals_are_exempt_where_source_numbers_are_not(tmp_path):
    repo = _repo(tmp_path, "def f(x):\n    return x\n", ratchet={})
    (repo / "vulture_whitelist.py").write_text("unread_handler\n_.unread_attribute\n",
                                               encoding="utf-8")
    (repo / "pkg" / "test_shipped.py").write_text(
        "def test_f():\n    assert len('abc') == 3\n", encoding="utf-8")
    (repo / "tests").mkdir()
    (repo / "tests" / "test_mod.py").write_text(
        "def test_g():\n    assert len('abcd') == 4\n", encoding="utf-8")
    lint.assert_lint_is_clean(repo, repo / "pkg", repo / "tests")
    (repo / "pkg" / "mod.py").write_text("def f(x):\n    return x > 42\n", encoding="utf-8")
    with pytest.raises(AssertionError, match=r"mod\.py:2:\d+: PLR2004"):
        lint.assert_lint_is_clean(repo, repo / "pkg", repo / "tests")


def test_a_rule_whose_places_rise_past_its_count_is_named_with_every_place(tmp_path):
    repo = _repo(tmp_path, "def f(x):\n    return x > 42\n", ratchet={"PLR2004": 1})
    lint.assert_lint_is_clean(repo, repo / "pkg")
    (repo / "pkg" / "more.py").write_text("def g(x):\n    return x < 7\n", encoding="utf-8")
    with pytest.raises(AssertionError, match=r"(?s)PLR2004 has 2 places, more than the 1 "
                                             r"ruff\.toml counts.*mod\.py:2.*more\.py:2"):
        lint.assert_lint_is_clean(repo, repo / "pkg")


def test_a_rule_whose_places_fall_below_its_count_asks_for_the_lower_count(tmp_path):
    repo = _repo(tmp_path, "def f(x):\n    return x > 42\n", ratchet={"PLR2004": 2})
    with pytest.raises(AssertionError, match=r"PLR2004 has 1 places, fewer than the 2 "
                                             r"ruff\.toml counts: write 1 beside it there"):
        lint.assert_lint_is_clean(repo, repo / "pkg")


def test_a_rule_with_no_places_left_asks_to_come_off_the_ratchet(tmp_path):
    repo = _repo(tmp_path, "def f(x):\n    return x\n", ratchet={"PLR2004": 1})
    with pytest.raises(AssertionError,
                       match=r"PLR2004 has no places left: take it off ruff\.toml's ratchet"):
        lint.assert_lint_is_clean(repo, repo / "pkg")


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


def test_a_noqa_for_a_rule_this_config_does_not_run_is_not_unused(tmp_path):
    """Other gates run ruff with selects of their own (genau's argument scan is
    `ARG`), and a ratcheted rule is ignored, not gone: a marker for either is
    dormant, and RUF100 must leave it for the gate that reads it."""
    repo = _repo(tmp_path, "def f(a):  # noqa: ARG001\n    return 1\n")
    (repo / "ruff.toml").write_text(lint.render_config(["PLC0415"]), encoding="utf-8")
    (repo / "pkg" / "late.py").write_text(
        "print('first')\n\nimport os  # noqa: E402, PLC0415\n\nprint(os.sep)\n",
        encoding="utf-8")
    lint.assert_lint_is_clean(repo, repo / "pkg")


def test_only_the_named_trees_and_the_root_files_are_scanned(tmp_path):
    """A gate checks out siblings beside or inside the repo (funestra's runner
    puts shared_ui under it), and a checkout lives in `.claude/worktrees`: a scan of
    `.` reads all of them under this repo's config. The named directories and the
    root's own files are the repo."""
    repo = _repo(tmp_path, "def f():\n    return 1\n")
    nested = repo / "sibling_checkout" / "pkg"
    nested.mkdir(parents=True)
    (nested / "mod.py").write_text("import os\n", encoding="utf-8")
    (repo / "launch.py").write_text("def g():\n    return 2\n", encoding="utf-8")
    lint.assert_lint_is_clean(repo, repo / "pkg")
    (repo / "launch.py").write_text("import os\n", encoding="utf-8")
    with pytest.raises(AssertionError, match=r"launch\.py:1:8: F401"):
        lint.assert_lint_is_clean(repo, repo / "pkg")

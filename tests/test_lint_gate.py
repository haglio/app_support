from __future__ import annotations

import subprocess
import tomllib
from pathlib import Path

import pytest

from app_support import lint


def test_the_rendered_config_carries_the_familys_numbers():
    config = tomllib.loads(lint.render_config())
    assert config["line-length"] == 100
    assert config["format"]["quote-style"] == "double"
    assert {"F", "E", "W", "I", "UP", "B", "PL", "PT", "RUF"} <= set(config["lint"]["select"])
    assert config["lint"]["ignore"] == ["E501", "BLE001", "S110", "PLR0913", "PLR0917", "PLR2004",
                                        "RUF001", "RUF002", "RUF003", "SIM117", "ISC004", "PLC3002"]


def test_a_repos_ratchet_survives_the_round_trip(tmp_path):
    written = tmp_path / "ruff.toml"
    written.write_text(lint.render_config(["PT018", "PLC0415"]), encoding="utf-8")
    assert lint.ratchet_of(written) == ("PT018", "PLC0415")
    lint.assert_config_is_the_familys(written)


def test_a_counted_ratchet_keeps_each_rules_places_through_the_round_trip(tmp_path):
    written = tmp_path / "ruff.toml"
    written.write_text(lint.render_config({"PLC0415": 12, "PT018": 3}), encoding="utf-8")
    assert lint.ratchet_of(written) == {"PLC0415": 12, "PT018": 3}
    lint.assert_config_is_the_familys(written)


def test_an_empty_counted_ratchet_keeps_the_exemptions_through_the_round_trip(tmp_path):
    written = tmp_path / "ruff.toml"
    written.write_text(lint.render_config({}), encoding="utf-8")
    assert lint.ratchet_of(written) == {}
    lint.assert_config_is_the_familys(written)


def test_a_config_that_drifted_anywhere_but_its_ratchet_is_refused(tmp_path):
    drifted = tmp_path / "ruff.toml"
    drifted.write_text(lint.render_config(["PLC0415"]).replace("line-length = 100", "line-length = 120"),
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


def test_names_in_a_dead_code_whitelist_are_no_findings(tmp_path):
    repo = _repo(tmp_path, "def f(x):\n    return x\n", ratchet={})
    (repo / "vulture_whitelist.py").write_text("unread_handler\n_.unread_attribute\n",
                                               encoding="utf-8")
    lint.assert_lint_is_clean(repo, repo / "pkg")


def test_a_number_compared_against_and_a_long_list_of_arguments_are_no_findings(tmp_path):
    lint.assert_lint_is_clean(_repo(tmp_path, "def f(a, b, c, d, e, f, g):\n    return a > 42\n"))


AN_IMPORT_INSIDE_A_FUNCTION = "def f():\n    import os\n    return os.sep\n"


def test_a_rule_whose_places_rise_past_its_count_is_named_with_every_place(tmp_path):
    repo = _repo(tmp_path, AN_IMPORT_INSIDE_A_FUNCTION, ratchet={"PLC0415": 1})
    lint.assert_lint_is_clean(repo, repo / "pkg")
    (repo / "pkg" / "more.py").write_text("def g():\n    import sys\n    return sys.path\n", encoding="utf-8")
    with pytest.raises(AssertionError, match=r"(?s)PLC0415 has 2 places, more than the 1 "
                                             r"ruff\.toml counts.*mod\.py:2.*more\.py:2"):
        lint.assert_lint_is_clean(repo, repo / "pkg")


def test_a_rule_whose_places_fall_below_its_count_asks_for_the_lower_count(tmp_path):
    repo = _repo(tmp_path, AN_IMPORT_INSIDE_A_FUNCTION, ratchet={"PLC0415": 2})
    with pytest.raises(AssertionError, match=r"PLC0415 has 1 places, fewer than the 2 "
                                             r"ruff\.toml counts: write 1 beside it there"):
        lint.assert_lint_is_clean(repo, repo / "pkg")


def test_a_rule_with_no_places_left_asks_to_come_off_the_ratchet(tmp_path):
    repo = _repo(tmp_path, "def f(x):\n    return x\n", ratchet={"PLC0415": 1})
    with pytest.raises(AssertionError,
                       match=r"PLC0415 has no places left: take it off ruff\.toml's ratchet"):
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
    repo = _repo(tmp_path, "def f(a):  # noqa: ARG001\n    return 1\n")
    (repo / "ruff.toml").write_text(lint.render_config(["PLC0415"]), encoding="utf-8")
    (repo / "pkg" / "late.py").write_text(
        "print('first')\n\nimport os  # noqa: E402, PLC0415\n\nprint(os.sep)\n",
        encoding="utf-8")
    lint.assert_lint_is_clean(repo, repo / "pkg")


def test_only_the_named_trees_and_the_root_files_are_scanned(tmp_path):
    repo = _repo(tmp_path, "def f():\n    return 1\n")
    nested = repo / "sibling_checkout" / "pkg"
    nested.mkdir(parents=True)
    (nested / "mod.py").write_text("import os\n", encoding="utf-8")
    (repo / "launch.py").write_text("def g():\n    return 2\n", encoding="utf-8")
    lint.assert_lint_is_clean(repo, repo / "pkg")
    (repo / "launch.py").write_text("import os\n", encoding="utf-8")
    with pytest.raises(AssertionError, match=r"launch\.py:1:8: F401"):
        lint.assert_lint_is_clean(repo, repo / "pkg")


def test_a_ruff_that_is_not_installed_is_not_an_answer(tmp_path):
    def missing(root, *args):
        return subprocess.CompletedProcess(args, 1, "", "No module")

    with pytest.raises(lint.LintDidNotRun, match="not installed"):
        lint.ruff_version(tmp_path, run=missing)


def test_a_rule_ruff_refuses_is_not_a_clean_scan(tmp_path):
    repo = _repo(tmp_path, "x = 1\n")
    with pytest.raises(lint.LintDidNotRun, match="exited 2"):
        lint.findings_for_rules(repo, ["NOT-A-RULE"], repo / "pkg")


def test_findings_for_named_rules_hold_whatever_the_repos_config_excludes(tmp_path):
    repo = _repo(tmp_path, "import os\n")
    with (repo / "ruff.toml").open("a", encoding="utf-8") as config:
        config.write('\nforce-exclude = true\nexclude = ["pkg"]\n')
    assert [line.split()[1] for line in lint.findings_for_rules(repo, ["F401"], repo / "pkg")] == ["F401"]

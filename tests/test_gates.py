"""Tests for the family's gates, which a repo gets by naming ``app_support.gates.pytest_plugin``.

Every package, project and finding here is invented.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from consumer_runs import run_pytest_in

from app_support import coverage_gate, lint
from app_support.gates import Checkout

GATED = "-p no:cacheprovider -p app_support.gates.pytest_plugin --timeout=60 --timeout-method=thread"
A_PROJECT = """\
[project]
name = "{name}"
requires-python = ">=3.14"
dependencies = ["app-support @ git+https://github.com/haglio/app_support@v0.1.300"]
[project.optional-dependencies]
dev = ["pytest-timeout>=2.4,<3"]
[tool.haglio]
siblings = ["app_support"]
"""
A_GATE = """\
jobs:
  suite:
    runs-on: windows-latest
    timeout-minutes: 10
    steps:
      - uses: actions/setup-python@v5
        with:
          python-version: "3.14"
"""
EVERY_REPOSITORYS_GATES = 20


def _checkout(root: Path, *files: str, project: str = "example") -> Checkout:
    root.mkdir(parents=True, exist_ok=True)
    for name in files:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("", encoding="utf-8")
    (root / "pyproject.toml").write_text(f'[project]\nname = "{project}"\n', encoding="utf-8")
    return Checkout(root)


class TestWhatACheckoutHolds:
    def test_its_code_is_its_packages_its_root_modules_and_its_tools(self, tmp_path: Path):
        checkout = _checkout(tmp_path, "one/__init__.py", "two/__init__.py", "main.py",
                             "tools/fix.py", "tests/test_one.py", "vulture_whitelist.py")

        assert checkout.code == (tmp_path / "one", tmp_path / "two", tmp_path / "main.py",
                                 tmp_path / "tools")

    def test_tools_kept_as_a_package_are_read_once(self, tmp_path: Path):
        checkout = _checkout(tmp_path, "one/__init__.py", "tools/__init__.py", "tools/fix.py")

        assert checkout.code == (tmp_path / "one", tmp_path / "tools")

    def test_a_checkout_with_no_tools_has_none(self, tmp_path: Path):
        checkout = _checkout(tmp_path, "one/__init__.py", "tools/notes.txt")

        assert checkout.code == (tmp_path / "one",)

    def test_what_it_ships_is_its_packages_and_its_root_modules(self, tmp_path: Path):
        checkout = _checkout(tmp_path, "one/__init__.py", "main.py", "tools/fix.py")

        assert checkout.ships == (tmp_path / "one", tmp_path / "main.py")
        assert checkout.own_names == ("one", "main")

    def test_a_family_library_is_told_from_an_app_by_its_project(self, tmp_path: Path):
        assert _checkout(tmp_path / "a", project="shared-ui").is_a_library
        assert not _checkout(tmp_path / "b", project="someapp").is_a_library

    def test_its_numbers_for_a_gate_are_its_own_table_and_none_without_one(self, tmp_path: Path):
        checkout = _checkout(tmp_path, "one/__init__.py")
        (tmp_path / "pyproject.toml").write_text(
            '[project]\nname = "someapp"\n[tool.haglio.dead-code]\neach-package-alone = true\n',
            encoding="utf-8")

        assert checkout.numbers("dead-code") == {"each-package-alone": True}
        assert checkout.numbers("coverage") == {}

    def test_its_whitelist_is_found_under_either_spelling(self, tmp_path: Path):
        assert _checkout(tmp_path / "a", "vulture_whitelist.py").whitelist == tmp_path / "a" / "vulture_whitelist.py"
        assert _checkout(tmp_path / "b", "vulture_whitelist.txt").whitelist == tmp_path / "b" / "vulture_whitelist.txt"
        assert _checkout(tmp_path / "c", "one/__init__.py").whitelist is None


def _repo(root: Path, *, options: str = GATED, numbers: str = "", name: str = "example",
          files: dict[str, str] | None = None) -> Path:
    """A repository that keeps every rule the family's gates hold it to."""
    every = {
        "pyproject.toml": (A_PROJECT.format(name=name) + numbers
                           + f'[tool.pytest.ini_options]\naddopts = "{options}"\n'),
        "ruff.toml": lint.render_config(),
        ".github/workflows/merge-gate.yml": A_GATE,
        "example/__init__.py": "",
        "example/app.py": 'def main():\n    return 1\n\n\nif __name__ == "__main__":\n    main()\n',
        "tests/test_example.py": "from example.app import main\n\n\ndef test_main():\n    assert main() == 1\n",
        **(files or {}),
    }
    for name_, text in every.items():
        path = root / name_
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return root


class TestTheGatesPlugin:
    def test_a_repo_that_keeps_every_rule_passes_every_gate(self, tmp_path: Path):
        done = run_pytest_in(_repo(tmp_path))

        assert done.returncode == 0, done.stdout
        assert f"{EVERY_REPOSITORYS_GATES + 1} passed" in done.stdout, done.stdout

    @pytest.mark.parametrize(("broken", "goes_red"), [
        ({"example/app.py": 'UNREAD = 1\n\n\ndef main():\n    return 1\n\n\nif __name__ == "__main__":\n    main()\n'},
         "test_no_module_level_constant_goes_unread"),
        ({"example/extra.py": "import nowhere_to_be_found\n"}, "test_every_third_party_import_is_declared"),
        ({"ruff.toml": lint.render_config() + "# drifted\n"}, "test_the_ruff_config_is_the_familys"),
        ({"launch_example.vbs": "WScript.Echo 1\n"}, "test_every_launcher_is_what_its_spec_renders"),
        ({".github/workflows/merge-gate.yml": A_GATE.replace("    timeout-minutes: 10\n", "")},
         "test_every_workflow_job_runs_under_its_own_clock"),
    ])
    def test_a_repo_that_breaks_a_rule_is_named_by_the_gate_that_holds_it(
            self, tmp_path: Path, broken: dict[str, str], goes_red: str):
        done = run_pytest_in(_repo(tmp_path, files=broken))

        assert done.returncode == 1, done.stdout
        assert f"::{goes_red} - " in done.stdout, done.stdout

    def test_what_a_repo_allows_is_read_from_its_numbers(self, tmp_path: Path):
        a_helper_nothing_calls = {"tests/helpers.py": "def never_called():\n    return 1\n"}

        done = run_pytest_in(_repo(tmp_path, files=a_helper_nothing_calls,
                                   numbers='[tool.haglio.dead-code]\nunread-test-helpers = ["never_called"]\n'))

        assert done.returncode == 0, done.stdout

    @pytest.mark.parametrize(("name", "goes_red"), [("shared-ui", False), ("example", True)])
    def test_a_librarys_tests_count_as_reading_it_and_an_apps_do_not(
            self, tmp_path: Path, name: str, goes_red: bool):
        read_only_by_its_tests = {
            "example/record.py": "from dataclasses import dataclass\n\n\n@dataclass\nclass Record:\n    kept: int\n",
            "tests/test_record.py": ("from example.record import Record\n\n\n"
                                     "def test_record():\n    assert Record(kept=1).kept == 1\n"),
        }

        done = run_pytest_in(_repo(tmp_path, name=name, files=read_only_by_its_tests))

        assert ("::test_no_dataclass_field_goes_unread - " in done.stdout) == goes_red, done.stdout

    @pytest.mark.parametrize(("numbers", "returncode"), [
        ("", 0), ("[tool.haglio.dead-code]\neach-package-alone = true\n", 1)])
    def test_packages_scanned_each_alone_cannot_hide_each_others_dead_code(
            self, tmp_path: Path, numbers: str, returncode: int):
        sharing_a_name = {"alpha/__init__.py": "", "alpha/mod.py": "def helper():\n    return 1\n",
                          "beta/__init__.py": "",
                          "beta/mod.py": "def helper():\n    return 2\n\n\nhelper()\n"}

        done = run_pytest_in(_repo(tmp_path, numbers=numbers, files=sharing_a_name))

        assert done.returncode == returncode, done.stdout

    @pytest.mark.parametrize(("numbers", "returncode"), [
        ("[tool.haglio.dead-code]\napps-are-callers = true\n", 0), ("", 1)])
    def test_a_library_whose_apps_are_its_callers_counts_what_they_use(
            self, tmp_path: Path, checkout_tracking, numbers: str, returncode: int):
        library = _repo(tmp_path / "widgetlib", numbers=numbers, files={
            "widgetlib/__init__.py": "", "widgetlib/api.py": "def published():\n    return 1\n"})
        checkout_tracking("someapp", {"parlour.py": "from widgetlib.api import published\n\npublished()\n"})

        done = run_pytest_in(library)

        assert done.returncode == returncode, done.stdout

    def test_a_run_that_names_one_file_leaves_the_gates_alone(self, tmp_path: Path):
        done = run_pytest_in(_repo(tmp_path), "tests/test_example.py")

        assert done.returncode == 0, done.stdout
        assert "1 passed" in done.stdout, done.stdout

    def test_the_coverage_config_is_checked_only_where_the_coverage_floor_is_asked_for(self, tmp_path: Path):
        not_unit_tested = (coverage_gate.NotUnitTested("example/shell.py", "needs a screen"),)
        repo = _repo(tmp_path, options=f"{GATED} -p app_support.coverage_gate --cov --cov-report=",
                     numbers=('[tool.haglio.coverage]\nnot-unit-tested = '
                              '[{ path = "example/shell.py", because = "needs a screen" }]\n'),
                     files={".coveragerc": coverage_gate.render_config(not_unit_tested),
                            "example/shell.py": ""})

        done = run_pytest_in(repo)

        assert done.returncode == 0, done.stdout
        assert f"{EVERY_REPOSITORYS_GATES + 2} passed" in done.stdout, done.stdout

    def test_a_package_every_app_installs_is_held_to_a_version_an_app_can_pin(self, tmp_path: Path):
        done = run_pytest_in(_repo(tmp_path, name="shared-ui"))

        assert done.returncode == 1, done.stdout
        assert "test_the_version_comes_from_the_tag" in done.stdout, done.stdout

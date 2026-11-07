from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest
from armed_guard import arm_where_the_guard_looks
from consumer_runs import run_pytest_in
from production_machine import git

from app_support.sanitize import find_violations, test_tracked_tree

APP_SUPPORT = Path(__file__).resolve().parents[1]
TERM = "plantedterm"

PYPROJECT = """\
[tool.pytest.ini_options]
addopts = "-p no:cacheprovider -p app_support.sanitize.pytest_plugin"
"""

CONFTEST_REFUSING_LOCKED_MD = """\
from pathlib import Path

_open = Path.open


def _refuse_locked_md(path, *args, **kwargs):
    if path.name == "locked.md":
        raise PermissionError(13, "Permission denied", str(path))
    return _open(path, *args, **kwargs)


Path.open = _refuse_locked_md
"""

CONFTEST_NAMING_A_TEST_FILE_FIRST = """\
from pathlib import Path

import pytest


@pytest.hookimpl(tryfirst=True)
def pytest_configure(config):
    config.args.append(str(Path(__file__).with_name("test_local.py")))
"""


class TestTheControlWordTheCheckCarries:
    def _file(self, tmp_path: Path, text: str) -> Path:
        path = tmp_path / "notes.md"
        path.write_text(text, encoding="utf-8")
        return path

    def test_the_first_whole_word_of_four_letters_is_taken(self, tmp_path: Path):
        path = self._file(tmp_path, "a bc def ordinary prose here")

        assert test_tracked_tree._a_control_word_from([path], []) == "ordinary"

    def test_a_word_inside_a_longer_one_is_not_taken(self, tmp_path: Path):
        path = self._file(tmp_path, "unremarkable_compound plain")

        assert test_tracked_tree._a_control_word_from([path], []) == "plain"

    def test_the_control_is_a_word_the_matchers_boundaries_let_the_scan_find(self, tmp_path: Path):
        text = "unremarkable_compound plain"
        path = self._file(tmp_path, text)

        control = test_tracked_tree._a_control_word_from([path], [])

        assert find_violations(text, [control])

    def test_the_control_rides_in_the_one_scan_the_terms_do(self, tmp_path: Path):
        scans: list[list[str]] = []

        def recording(paths, terms, *, root):
            scans.append(list(terms))
            return []

        test_tracked_tree._one_scan_of_the_terms_and_the_control(
            [tmp_path / "notes.md"], [TERM], "ordinary", tmp_path, scan=recording)

        assert scans == [[TERM, "ordinary"]]

    def test_a_plural_is_passed_over_since_the_guard_scans_for_its_stem(self, tmp_path: Path):
        path = self._file(tmp_path, "notes belong here")

        assert test_tracked_tree._a_control_word_from([path], []) == "belong"

    def test_a_word_carrying_a_term_is_passed_over_so_no_real_hit_passes_as_the_control(self, tmp_path: Path):
        path = self._file(tmp_path, f"{TERM} and something ordinary")

        assert test_tracked_tree._a_control_word_from([path], [TERM]) == "something"

    def test_a_file_that_cannot_be_read_is_passed_over(self, tmp_path: Path):
        gone = tmp_path / "gone.md"
        readable = self._file(tmp_path, "ordinary prose")

        assert test_tracked_tree._a_control_word_from([gone, readable], []) == "ordinary"

    def test_the_control_comes_out_of_the_tree_so_nothing_readable_means_no_control(self, tmp_path: Path):
        binary = tmp_path / "mark.ico"
        binary.write_bytes(bytes(range(256)))

        assert test_tracked_tree._a_control_word_from(
            [tmp_path / "gone.md", binary], []) is None


class TestTheGuardPlugin:
    def _repo(self, tmp_path: Path, *, blocklist: str | None, tracked: str) -> Path:
        repo = tmp_path / "family" / "repo"
        repo.mkdir(parents=True)
        (repo / "pyproject.toml").write_text(PYPROJECT, encoding="utf-8")
        if blocklist is not None:
            arm_where_the_guard_looks(repo, blocklist)
        (repo / "notes.md").write_text(tracked, encoding="utf-8")
        git("init", "-b", "main", cwd=repo)
        git("config", "user.email", "guard@example.test", cwd=repo)
        git("config", "user.name", "Guard Test", cwd=repo)
        git("add", ".", cwd=repo)
        git("commit", "-m", "seed", "--no-verify", cwd=repo)
        return repo

    def test_a_planted_term_in_a_tracked_file_fails_the_run(self, tmp_path: Path):
        repo = self._repo(
            tmp_path, blocklist=f"{TERM}\n", tracked=f"this has {TERM} in it\n")

        done = run_pytest_in(repo)

        assert done.returncode != 0, done.stdout
        assert "notes.md" in done.stdout

    @pytest.mark.parametrize("started_on", [[], ["."]], ids=["nothing named", "its directory"])
    def test_a_planted_term_fails_a_run_that_names_the_clock_checks_too(
            self, tmp_path: Path, started_on: list[str]):
        repo = self._repo(
            tmp_path, blocklist=f"{TERM}\n", tracked=f"this has {TERM} in it\n")
        (repo / "pyproject.toml").write_text(PYPROJECT.replace(
            "pytest_plugin", "pytest_plugin -p app_support.clocks.pytest_plugin"), encoding="utf-8")

        done = run_pytest_in(repo, *started_on)

        assert "notes.md" in done.stdout, done.stdout

    def test_a_planted_term_fails_a_full_run_other_code_has_already_named_a_test_file_in(
            self, tmp_path: Path):
        repo = self._repo(
            tmp_path, blocklist=f"{TERM}\n", tracked=f"this has {TERM} in it\n")
        (repo / "test_local.py").write_text("def test_local():\n    assert True\n", encoding="utf-8")
        (repo / "conftest.py").write_text(CONFTEST_NAMING_A_TEST_FILE_FIRST, encoding="utf-8")

        done = run_pytest_in(repo)

        assert "notes.md" in done.stdout, done.stdout

    def test_a_clean_tracked_tree_passes(self, tmp_path: Path):
        repo = self._repo(tmp_path, blocklist=f"{TERM}\n", tracked="perfectly clean\n")

        assert run_pytest_in(repo).returncode == 0

    def test_a_checkout_with_no_blocklist_skips_rather_than_pass_as_if_scanned(self, tmp_path: Path):
        repo = self._repo(tmp_path, blocklist=None, tracked=f"this has {TERM} in it\n")

        done = run_pytest_in(repo)

        assert done.returncode == 0
        assert "1 passed" not in done.stdout
        assert "1 skipped" in done.stdout
        assert "NOT scanned" in done.stdout

    def test_a_source_tree_with_no_git_at_all_is_not_taken_down_either(self, tmp_path: Path):
        repo = tmp_path / "unpacked"
        (repo / "tests").mkdir(parents=True)
        (repo / "pyproject.toml").write_text(PYPROJECT, encoding="utf-8")
        (repo / "tests" / "test_local.py").write_text(
            "def test_local():\n    assert True\n", encoding="utf-8")

        done = run_pytest_in(repo)

        assert done.returncode == 0, done.stdout
        assert "1 passed, 1 skipped" in done.stdout
        assert "NOT scanned" in done.stdout

    def test_the_reason_rides_in_the_warnings_which_a_bare_q_run_prints(self, tmp_path: Path):
        repo = self._repo(tmp_path, blocklist=None, tracked="perfectly clean\n")

        done = run_pytest_in(repo)

        assert "warnings summary" in done.stdout
        assert "SANITIZE GUARD UNARMED" in done.stdout

    def test_an_untracked_file_cannot_leak_so_it_is_not_the_repos_problem(self, tmp_path: Path):
        repo = self._repo(tmp_path, blocklist=f"{TERM}\n", tracked="perfectly clean\n")
        (repo / "scratch.md").write_text(f"this has {TERM} in it\n", encoding="utf-8")

        assert run_pytest_in(repo).returncode == 0

    def test_an_armed_checkout_with_nothing_tracked_is_refused_not_reported_clean(
        self, tmp_path: Path,
    ):
        repo = tmp_path / "family" / "empty"
        repo.mkdir(parents=True)
        (repo / "pyproject.toml").write_text(PYPROJECT, encoding="utf-8")
        arm_where_the_guard_looks(repo, f"{TERM}\n")
        (repo / "test_local.py").write_text(
            "def test_local():\n    assert True\n", encoding="utf-8")
        git("init", "-b", "main", cwd=repo)

        done = run_pytest_in(repo)

        assert done.returncode != 0, done.stdout
        assert "no files at all" in done.stdout

    def test_a_tracked_name_with_a_space_in_it_is_one_file_and_is_scanned(
        self, tmp_path: Path,
    ):
        repo = self._repo(tmp_path, blocklist=f"{TERM}\n", tracked="perfectly clean\n")
        (repo / "release notes.md").write_text(
            f"this has {TERM} in it\n", encoding="utf-8")
        git("add", ".", cwd=repo)
        git("commit", "-m", "notes", "--no-verify", cwd=repo)

        done = run_pytest_in(repo)

        assert done.returncode != 0, done.stdout

    def test_a_walk_that_could_read_none_of_the_tree_is_refused_not_reported_clean(
        self, tmp_path: Path,
    ):
        repo = tmp_path / "family" / "gone"
        repo.mkdir(parents=True)
        arm_where_the_guard_looks(repo, f"{TERM}\n")
        pytest_reads_this_but_the_walk_never_will = repo / "pyproject.toml"
        pytest_reads_this_but_the_walk_never_will.write_text(PYPROJECT, encoding="utf-8")
        (repo / "notes.md").write_text(
            f"this has {TERM} in it\n", encoding="utf-8")
        git("init", "-b", "main", cwd=repo)
        git("config", "user.email", "guard@example.test", cwd=repo)
        git("config", "user.name", "Guard Test", cwd=repo)
        git("add", "notes.md", cwd=repo)
        git("commit", "-m", "seed", "--no-verify", cwd=repo)
        (repo / "notes.md").unlink()

        done = run_pytest_in(repo)

        assert done.returncode != 0, done.stdout
        assert "read no text at all" in done.stdout

    def test_a_tracked_file_that_cannot_be_opened_fails_the_run(self, tmp_path: Path):
        repo = self._repo(tmp_path, blocklist=f"{TERM}\n", tracked="perfectly clean\n")
        (repo / "locked.md").write_text("ordinary prose\n", encoding="utf-8")
        git("add", "locked.md", cwd=repo)
        git("commit", "-m", "locked", "--no-verify", cwd=repo)
        (repo / "conftest.py").write_text(CONFTEST_REFUSING_LOCKED_MD, encoding="utf-8")

        done = run_pytest_in(repo)

        assert done.returncode != 0, done.stdout
        assert "locked.md:0  (could not be read: PermissionError)" in done.stdout

    def test_pytest_tests_the_familys_own_command_is_still_a_run_of_the_whole_tree(self, tmp_path: Path):
        repo = self._repo(
            tmp_path, blocklist=f"{TERM}\n", tracked=f"this has {TERM} in it\n")
        (repo / "tests").mkdir()
        (repo / "tests" / "test_local.py").write_text(
            "def test_local():\n    assert True\n", encoding="utf-8")

        assert run_pytest_in(repo, "tests").returncode != 0

    def test_a_subdirectory_run_still_enforces_since_testpaths_is_relative_to_the_root(self, tmp_path: Path):
        repo = self._repo(
            tmp_path, blocklist=f"{TERM}\n", tracked=f"this has {TERM} in it\n")
        (repo / "pyproject.toml").write_text(
            PYPROJECT + 'testpaths = ["tests"]\n', encoding="utf-8")
        (repo / "tests").mkdir()
        (repo / "tests" / "test_local.py").write_text(
            "def test_local():\n    assert True\n", encoding="utf-8")

        done = run_pytest_in(repo / "tests")

        assert done.returncode != 0, done.stdout

    def test_a_configuration_kept_in_a_subfolder_still_scans_the_whole_checkout(self, tmp_path: Path):
        repo = self._repo(
            tmp_path, blocklist=f"{TERM}\n", tracked=f"ordinary prose with {TERM} in it\n")
        (repo / "pyproject.toml").unlink()
        (repo / "tests").mkdir()
        (repo / "tests" / "pyproject.toml").write_text(PYPROJECT, encoding="utf-8")
        (repo / "tests" / "test_local.py").write_text(
            "def test_local():\n    assert True\n", encoding="utf-8")

        done = run_pytest_in(repo, "tests")

        assert done.returncode != 0, done.stdout
        assert "notes.md" in done.stdout

    def test_a_run_that_names_one_file_leaves_the_tree_alone(self, tmp_path: Path):
        repo = self._repo(
            tmp_path, blocklist=f"{TERM}\n", tracked=f"this has {TERM} in it\n")
        (repo / "tests").mkdir()
        target = repo / "tests" / "test_local.py"
        target.write_text("def test_local():\n    assert True\n", encoding="utf-8")

        done = run_pytest_in(repo, str(target))

        assert done.returncode == 0, done.stdout
        assert "1 passed" in done.stdout

    def test_a_run_that_names_one_test_leaves_the_tree_alone(self, tmp_path: Path):
        repo = self._repo(
            tmp_path, blocklist=f"{TERM}\n", tracked=f"this has {TERM} in it\n")
        (repo / "tests").mkdir()
        target = repo / "tests" / "test_local.py"
        target.write_text("def test_local():\n    assert True\n", encoding="utf-8")

        done = run_pytest_in(repo, f"{target}::test_local")

        assert done.returncode == 0, done.stdout
        assert "1 passed" in done.stdout

    def test_the_guard_a_git_hook_imports_never_reaches_for_pytest(self):
        probe = (
            "import sys, app_support.sanitize\n"
            "print(sorted(m for m in sys.modules if m.startswith('pytest')"
            " or m.startswith('_pytest')))\n"
        )
        done = subprocess.run(
            [sys.executable, "-c", probe],
            cwd=APP_SUPPORT, env={**os.environ, "PYTHONPATH": str(APP_SUPPORT)},
            capture_output=True, text=True, check=False,
        )

        assert done.returncode == 0, done.stderr
        assert done.stdout.strip() == "[]", done.stdout

    def test_without_the_plugin_line_nothing_is_contributed(self, tmp_path: Path):
        repo = self._repo(
            tmp_path, blocklist=f"{TERM}\n", tracked=f"this has {TERM} in it\n")
        (repo / "pyproject.toml").write_text(
            '[tool.pytest.ini_options]\naddopts = "-p no:cacheprovider"\n',
            encoding="utf-8")

        done = run_pytest_in(repo)

        # Nothing to run at all, which pytest reports as exit code 5.
        assert done.returncode == 5, done.stdout

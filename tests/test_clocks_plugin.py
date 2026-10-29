"""Tests for the clock checks a repo gets by naming ``app_support.clocks.pytest_plugin``.

The cases that matter run a real pytest against a throwaway repo, because a
plugin that quietly contributed nothing would look exactly like a repo whose
clocks are all in place.
"""
from __future__ import annotations

from pathlib import Path

from consumer_runs import run_pytest_in

from app_support.clocks import jobs_without_a_clock, per_test_clock_s

CLOCKED_OPTIONS = "-p no:cacheprovider -p app_support.clocks.pytest_plugin --timeout=60 --timeout-method=thread"
DECLARED = '[project]\nname = "example"\n[project.optional-dependencies]\ndev = ["pytest-timeout>=2.4,<3"]\n'
A_CLOCKED_JOB = "jobs:\n  suite:\n    runs-on: windows-latest\n    timeout-minutes: 10\n"


class TestReadingTheClocks:
    def test_the_per_test_budget_is_the_one_the_options_declare(self):
        assert per_test_clock_s(["-p", "no:cacheprovider", "--timeout=240", "--timeout-method=thread"]) == 240

    def test_options_with_no_budget_declare_none(self):
        assert per_test_clock_s(["-p", "no:cacheprovider", "--timeout-method=thread"]) is None

    def test_a_budget_of_zero_is_none_since_pytest_timeout_reads_it_as_off(self):
        assert per_test_clock_s(["--timeout=0"]) is None

    def test_a_job_with_a_clock_of_its_own_is_clocked(self):
        assert jobs_without_a_clock(A_CLOCKED_JOB) == []

    def test_a_job_without_one_is_named(self):
        assert jobs_without_a_clock("jobs:\n  suite:\n    runs-on: windows-latest\n") == ["suite"]

    def test_a_job_that_calls_the_familys_gate_is_clocked_by_it(self):
        workflow = "jobs:\n  full-suite:\n    uses: haglio/.github/.github/workflows/merge-gate.yml@main\n"

        assert jobs_without_a_clock(workflow) == []

    def test_a_steps_clock_is_not_the_jobs(self):
        workflow = ("jobs:\n  suite:\n    runs-on: windows-latest\n    steps:\n"
                    "      - run: pytest\n        timeout-minutes: 10\n")

        assert jobs_without_a_clock(workflow) == ["suite"]

    def test_a_comment_at_the_margin_between_two_jobs_does_not_end_them(self):
        """A full-line separator between two jobs is legal YAML; read as the end
        of the block, it would wave through every job below it."""
        workflow = A_CLOCKED_JOB + "# the second job\n  lint:\n    runs-on: windows-latest\n"

        assert jobs_without_a_clock(workflow) == ["lint"]

    def test_what_follows_the_jobs_is_not_read_as_one(self):
        workflow = "jobs:\n  suite:\n    timeout-minutes: 10\nconcurrency:\n  group: gate\n"

        assert jobs_without_a_clock(workflow) == []


class TestTheClockPlugin:
    def _repo(self, tmp_path: Path, *, options: str = CLOCKED_OPTIONS, project: str = DECLARED,
              workflow: str | None = A_CLOCKED_JOB) -> Path:
        repo = tmp_path / "family" / "repo"
        repo.mkdir(parents=True)
        (repo / "pyproject.toml").write_text(
            f'{project}[tool.pytest.ini_options]\naddopts = "{options}"\n', encoding="utf-8")
        if workflow is not None:
            (repo / ".github" / "workflows").mkdir(parents=True)
            (repo / ".github" / "workflows" / "gate.yml").write_text(workflow, encoding="utf-8")
        return repo

    def test_a_repo_with_every_clock_passes_all_three_checks(self, tmp_path: Path):
        done = run_pytest_in(self._repo(tmp_path))

        assert done.returncode == 0, done.stdout
        assert "3 passed" in done.stdout, done.stdout

    def test_a_repo_whose_options_declare_no_per_test_clock_fails_the_run(self, tmp_path: Path):
        repo = self._repo(tmp_path, options="-p no:cacheprovider -p app_support.clocks.pytest_plugin")

        done = run_pytest_in(repo)

        assert done.returncode == 1, done.stdout
        assert "test_every_test_runs_under_its_own_clock" in done.stdout, done.stdout

    def test_a_workflow_job_with_no_clock_fails_the_run(self, tmp_path: Path):
        repo = self._repo(tmp_path, workflow="jobs:\n  suite:\n    runs-on: windows-latest\n")

        done = run_pytest_in(repo)

        assert done.returncode == 1, done.stdout
        assert "test_every_workflow_job_runs_under_its_own_clock" in done.stdout, done.stdout

    def test_a_repo_with_no_workflows_is_told_so_rather_than_passed(self, tmp_path: Path):
        done = run_pytest_in(self._repo(tmp_path, workflow=None))

        assert done.returncode == 1, done.stdout
        assert "no workflows found" in done.stdout, done.stdout

    def test_a_clock_whose_plugin_ci_never_installs_fails_the_run(self, tmp_path: Path):
        done = run_pytest_in(self._repo(tmp_path, project='[project]\nname = "example"\n'))

        assert done.returncode == 1, done.stdout
        assert "test_the_plugin_that_keeps_the_clock_is_declared_where_ci_installs_it" in done.stdout, done.stdout

    def test_a_run_that_names_one_file_leaves_the_clocks_alone(self, tmp_path: Path):
        repo = self._repo(tmp_path, options="-p no:cacheprovider -p app_support.clocks.pytest_plugin")
        (repo / "test_local.py").write_text("def test_local():\n    assert True\n", encoding="utf-8")

        done = run_pytest_in(repo, "test_local.py")

        assert done.returncode == 0, done.stdout
        assert "1 passed" in done.stdout, done.stdout

    def test_without_the_plugin_line_nothing_is_contributed(self, tmp_path: Path):
        repo = self._repo(tmp_path, options="-p no:cacheprovider")

        done = run_pytest_in(repo)

        # Nothing to run at all, which pytest reports as exit code 5.
        assert done.returncode == 5, done.stdout

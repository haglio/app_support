"""A fix on an agent's branch put into its app's production checkout now, ahead of shipping it the usual way."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from production_machine import Machine, a_process, git, pins

from app_support import hotfix

HOTFIXABLE = pins() + '\n[tool.haglio.hotfix]\nchecks = ["tests/test_launch.py"]\n'
PASSED_ONLY = '\n[tool.haglio.production]\ncommit-file = "state/passed.txt"\n'
PASSES_OVER_INTEGRATION = '\n[tool.pytest.ini_options]\ntestpaths = ["tests"]\nnorecursedirs = ["integration"]\n'


@pytest.fixture
def machine(tmp_path):
    return Machine(tmp_path)


@pytest.fixture
def production(machine):
    return machine.checkout(files={"pyproject.toml": HOTFIXABLE})


def a_branch(machine: Machine, production: Path, files: dict[str, str], *, name: str = "claude/the-fix") -> Path:
    place = machine.base / name.replace("/", "-")
    git("worktree", "add", "-q", "-b", name, str(place), "origin/main", cwd=production)
    for file, text in files.items():
        (place / file).parent.mkdir(parents=True, exist_ok=True)
        (place / file).write_text(text, encoding="utf-8")
    git("add", "-A", cwd=place)
    git("commit", "-q", "-m", "Fix the thing", cwd=place)
    return place


class Checks:
    def __init__(self, *, failing: bool = False) -> None:
        self.ran: list[tuple[Path, list[str], Path]] = []
        self.failing = failing

    def __call__(self, python: Path, tests: list[str], place: Path) -> None:
        self.ran.append((Path(python), list(tests), Path(place)))
        if self.failing:
            raise hotfix.Refused("tests/test_launch.py::test_it failed")


def route(machine: Machine, worktree: Path, *, checks: Checks | None = None) -> str:
    return hotfix.hotfix(worktree, run=machine.run, check=checks or Checks(),
                         bring_up=machine.bring_up)


class TestTheRoute:
    def test_a_fix_on_a_branch_reaches_its_production_checkout(self, machine, production):
        worktree = a_branch(machine, production, {"fix.txt": "fixed\n"})

        route(machine, worktree)

        assert (production / "fix.txt").read_text(encoding="utf-8") == "fixed\n"

    def test_the_hotfix_stands_for_the_commits_that_ship_the_same_fix_the_usual_way(self, machine, production):
        worktree = a_branch(machine, production, {"fix.txt": "fixed\n"})
        authored = git("log", "-1", "--format=%ae %at", cwd=worktree)

        route(machine, worktree)

        assert f"Hotfix-of: {authored}" in git("log", "-1", "--format=%B", cwd=production)

    def test_the_checks_are_the_ones_the_repo_names_and_the_tests_the_branch_changed(self, machine, production):
        worktree = a_branch(machine, production, {"fix.txt": "fixed\n", "tests/test_fix.py": "def test_it(): pass\n"})
        checks = Checks()

        route(machine, worktree, checks=checks)

        [(python, tests, place)] = checks.ran
        assert python == production / ".venv" / "Scripts" / "python.exe"
        assert tests == ["tests/test_launch.py", "tests/test_fix.py"]
        assert place not in (production, worktree)

    def test_the_tests_the_suite_passes_over_are_never_checked(self, machine):
        production = machine.checkout(files={"pyproject.toml": HOTFIXABLE + PASSES_OVER_INTEGRATION})
        worktree = a_branch(machine, production, {"tests/integration/test_room.py": "def test_it(): pass\n",
                                                  "tests/test_fix.py": "def test_it(): pass\n"})
        checks = Checks()

        route(machine, worktree, checks=checks)

        assert checks.ran[0][1] == ["tests/test_launch.py", "tests/test_fix.py"]

    def test_production_running_its_app_takes_the_hotfix_once_the_app_closes(self, machine, production):
        before = machine.head(production)
        worktree = a_branch(machine, production, {"fix.txt": "fixed\n"})

        said = hotfix.hotfix(worktree, run=machine.run, check=Checks(), bring_up=lambda checkout: machine.bring_up(
            checkout, in_use=lambda venvs: [a_process("Example-Example.exe")]))

        assert machine.head(production) == before
        assert machine.hotfix_asked_for(production) is not None
        assert "takes the hotfix" in said
        assert "Example-Example.exe" in said

    def test_a_second_hotfix_builds_on_the_first_one_production_has_not_taken_yet(self, machine, production):
        running = [a_process("Example-Example.exe")]
        waiting = lambda checkout: machine.bring_up(checkout, in_use=lambda venvs: running)  # noqa: E731
        first = a_branch(machine, production, {"one.txt": "fixed\n"}, name="claude/one")
        hotfix.hotfix(first, run=machine.run, check=Checks(), bring_up=waiting)
        asked_first = machine.hotfix_asked_for(production)
        second = a_branch(machine, production, {"two.txt": "fixed\n"}, name="claude/two")

        hotfix.hotfix(second, run=machine.run, check=Checks(), bring_up=waiting)
        running.clear()
        machine.bring_up(production)

        assert git("rev-parse", "HEAD^", cwd=production) == asked_first
        assert (production / "one.txt").is_file()
        assert (production / "two.txt").is_file()


class TestTheChecks:
    @staticmethod
    def a_checkout(tmp_path: Path, tests: dict[str, str]) -> Path:
        for name, text in tests.items():
            (tmp_path / "tests").mkdir(exist_ok=True)
            (tmp_path / "tests" / name).write_text(text, encoding="utf-8")
        return tmp_path

    def test_checks_that_pass_let_the_hotfix_through(self, tmp_path):
        place = self.a_checkout(tmp_path, {"test_ok.py": "def test_ok(): pass\n"})

        hotfix.run_checks(Path(sys.executable), ["tests/test_ok.py"], place)

    def test_a_check_that_fails_refuses_the_hotfix_and_says_which(self, tmp_path):
        place = self.a_checkout(tmp_path, {"test_ok.py": "def test_ok(): pass\n",
                                           "test_bad.py": "def test_bad(): assert False\n"})

        with pytest.raises(hotfix.Refused, match="test_bad"):
            hotfix.run_checks(Path(sys.executable), ["tests/test_ok.py", "tests/test_bad.py"], place)


class TestTheCommandLine:
    def test_a_refusal_is_said_and_ends_the_command_in_failure(self, machine, production, monkeypatch, capsys,
                                                               tmp_path):
        worktree = a_branch(machine, production, {"fix.txt": "fixed\n"})
        (worktree / "fix.txt").write_text("fixed again\n", encoding="utf-8")
        monkeypatch.chdir(worktree)

        assert hotfix.main([], state=tmp_path / "state") == 1
        assert capsys.readouterr().out.startswith("refused: this worktree has uncommitted changes")

    def test_production_is_brought_up_at_once_and_the_update_written_down(self, machine, production, tmp_path):
        hotfix_asked_for = machine.hotfix(production, {"fix.txt": "fixed\n"})

        outcome = hotfix.bring_up_now(production, state=tmp_path, in_use=lambda venvs: [])

        assert machine.head(production) == hotfix_asked_for
        assert outcome.said.startswith("moved from")
        assert (tmp_path / "production_update.json").is_file()


class TestWhatIsRefused:
    def test_a_fix_whose_check_fails_never_reaches_production(self, machine, production):
        before = machine.head(production)
        worktree = a_branch(machine, production, {"fix.txt": "fixed\n"})

        with pytest.raises(hotfix.Refused, match="test_it failed"):
            route(machine, worktree, checks=Checks(failing=True))

        assert machine.head(production) == before
        assert machine.hotfix_asked_for(production) is None

    def test_a_fix_that_needs_a_change_production_does_not_run_yet_is_refused(self, machine):
        production = machine.checkout(files={"pyproject.toml": HOTFIXABLE + PASSED_ONLY})
        (production / "state").mkdir()
        (production / "state" / "passed.txt").write_text(machine.head(production), encoding="utf-8")
        machine.ship(production, {"untested.txt": "new\n"})
        worktree = a_branch(machine, production, {"untested.txt": "fixed\n"})

        with pytest.raises(hotfix.Refused, match=r"untested\.txt"):
            route(machine, worktree)

        assert machine.hotfix_asked_for(production) is None

    def test_a_fix_that_moves_a_library_pin_is_refused(self, machine, production):
        worktree = a_branch(machine, production, {"pyproject.toml": HOTFIXABLE.replace(
            "dependencies = [\n", 'dependencies = [\n    "app-support @ git+https://github.com/haglio/app_support@v0.1.999",\n')})

        with pytest.raises(hotfix.Refused, match="shared code"):
            route(machine, worktree)

    def test_a_worktree_with_uncommitted_changes_is_refused(self, machine, production):
        worktree = a_branch(machine, production, {"fix.txt": "fixed\n"})
        (worktree / "fix.txt").write_text("fixed again\n", encoding="utf-8")

        with pytest.raises(hotfix.Refused, match="uncommitted"):
            route(machine, worktree)

    def test_a_branch_with_nothing_main_lacks_is_refused(self, machine, production):
        place = machine.base / "nothing"
        git("worktree", "add", "-q", "-b", "claude/nothing", str(place), "origin/main", cwd=production)

        with pytest.raises(hotfix.Refused, match="nothing"):
            route(machine, place)

    def test_a_hotfix_asked_for_by_another_session_meanwhile_is_never_overwritten(self, machine, production):
        worktree = a_branch(machine, production, {"fix.txt": "fixed\n"})
        theirs = machine.hotfix(production, {"theirs.txt": "fixed\n"})
        git("update-ref", "-d", "refs/haglio/hotfix", cwd=production)

        def another_session_asks_meanwhile(python, tests, place):
            git("update-ref", "refs/haglio/hotfix", theirs, cwd=production)

        with pytest.raises(hotfix.Refused, match="another hotfix"):
            hotfix.hotfix(worktree, run=machine.run, check=another_session_asks_meanwhile,
                          bring_up=machine.bring_up)

        assert machine.hotfix_asked_for(production) == theirs

    def test_a_repo_that_names_no_checks_is_refused(self, machine):
        production = machine.checkout()
        worktree = a_branch(machine, production, {"fix.txt": "fixed\n"})

        with pytest.raises(hotfix.Refused, match=r"\[tool\.haglio\.hotfix\]"):
            route(machine, worktree)

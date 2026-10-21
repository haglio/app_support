"""A fix on an agent's branch put into its app's production checkout now, ahead of shipping it the usual way."""
from __future__ import annotations

import dataclasses
import re
import sys
from pathlib import Path

import pytest
from production_machine import Machine, a_process, git, pins

from app_support import hotfix
from app_support.production_update import Outcome

CHECKS = '\n[tool.haglio.hotfix]\nchecks = ["tests/test_launch.py"]\n'
HOTFIXABLE = pins() + CHECKS
PASSED_ONLY = '\n[tool.haglio.production]\ncommit-file = "state/passed.txt"\n'
PASSES_OVER_INTEGRATION = '\n[tool.pytest.ini_options]\ntestpaths = ["tests"]\nnorecursedirs = ["integration"]\n'
LIBRARY = '[project]\nname = "funestra"\n'


@pytest.fixture
def machine(tmp_path):
    return Machine(tmp_path)


@pytest.fixture
def production(machine):
    return machine.checkout(files={"pyproject.toml": HOTFIXABLE})


def a_branch(machine: Machine, production: Path, files: dict[str, str], *, name: str = "claude/the-fix") -> Path:
    place = machine.base / f"{production.name}-{name.replace('/', '-')}"
    git("worktree", "add", "-q", "-b", name, str(place), "origin/main", cwd=production)
    for file, text in files.items():
        (place / file).parent.mkdir(parents=True, exist_ok=True)
        (place / file).write_text(text, encoding="utf-8")
    git("add", "-A", cwd=place)
    git("commit", "-q", "-m", "Fix the thing", cwd=place)
    return place


class Checks:
    def __init__(self, *, failing: bool = False) -> None:
        self.ran: list[tuple[Path, list[str], Path, list[Path]]] = []
        self.heads: list[list[str]] = []
        self.failing = failing

    def __call__(self, python: Path, tests: list[str], place: Path, pythonpath: list[Path]) -> None:
        self.ran.append((Path(python), list(tests), Path(place), list(pythonpath)))
        self.heads.append([git("rev-parse", "HEAD", cwd=entry) for entry in pythonpath])
        if self.failing:
            raise hotfix.Refused("tests/test_launch.py::test_it failed")


class Sweeps:
    def __init__(self, *, failing: bool = False) -> None:
        self.ran: list[tuple[Path, Path, list[Path]]] = []
        self.failing = failing

    def __call__(self, python: Path, place: Path, pythonpath: list[Path]) -> None:
        self.ran.append((Path(python), Path(place), list(pythonpath)))
        if self.failing:
            raise hotfix.Refused("example.app did not import")


def route(machine: Machine, worktree: Path, *, checks: Checks | None = None, sweeps: Sweeps | None = None,
          libraries: tuple[Path, ...] = (), bring_up=None) -> str:
    return hotfix.hotfix(worktree, libraries=libraries, run=machine.run, check=checks or Checks(),
                         sweep=sweeps or Sweeps(), bring_up=bring_up or machine.bring_up)


def the_shared_code(machine: Machine) -> Path:
    library = machine.checkout("funestra", venv=False, files={"pyproject.toml": LIBRARY, "engine.txt": "broken\n"})
    machine.release(library, "v0.1.1")
    return library


class TestTheRoute:
    def test_a_fix_on_a_branch_reaches_its_production_checkout(self, machine, production):
        worktree = a_branch(machine, production, {"fix.txt": "fixed\n"})

        route(machine, worktree)

        assert (production / "fix.txt").read_text(encoding="utf-8") == "fixed\n"

    def test_the_hotfix_stands_for_the_commits_that_ship_the_same_fix_the_usual_way(self, machine, production):
        worktree = a_branch(machine, production, {"fix.txt": "fixed\n"})
        authored = git("log", "-1", "--format=%ae %at", cwd=worktree)

        route(machine, worktree)

        assert f"Hotfix-of: {authored}\n" in git("log", "-1", "--format=%B", cwd=production) + "\n"

    def test_the_checks_are_the_ones_the_repo_names_and_the_tests_the_branch_changed(self, machine, production):
        worktree = a_branch(machine, production, {"fix.txt": "fixed\n", "tests/test_fix.py": "def test_it(): pass\n"})
        checks = Checks()

        route(machine, worktree, checks=checks)

        [(python, tests, place, pythonpath)] = checks.ran
        assert python == production / ".venv" / "Scripts" / "python.exe"
        assert tests == ["tests/test_launch.py", "tests/test_fix.py"]
        assert place not in (production, worktree)
        assert pythonpath == []

    def test_every_module_the_hotfix_ships_is_imported_before_production_takes_it(self, machine, production):
        worktree = a_branch(machine, production, {"fix.txt": "fixed\n"})
        sweeps = Sweeps()

        route(machine, worktree, sweeps=sweeps)

        [(python, place, _pythonpath)] = sweeps.ran
        assert python == production / ".venv" / "Scripts" / "python.exe"
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

        said = route(machine, worktree, bring_up=lambda checkout: machine.bring_up(
            checkout, in_use=lambda venvs: [a_process("Example-Example.exe")]))

        assert machine.head(production) == before
        assert machine.hotfix_asked_for(production) is not None
        assert "takes the hotfix" in said
        assert "Example-Example.exe" in said

    def test_production_that_took_the_hotfix_but_failed_to_finish_says_so(self, machine, production):
        worktree = a_branch(machine, production, {"fix.txt": "fixed\n"})

        said = route(machine, worktree, bring_up=lambda checkout: dataclasses.replace(
            machine.bring_up(checkout), said="failed: pip said no", failed=True))

        assert "runs the hotfix" in said
        assert "pip said no" in said

    def test_a_second_hotfix_builds_on_the_first_one_production_has_not_taken_yet(self, machine, production):
        running = [a_process("Example-Example.exe")]
        waiting = lambda checkout: machine.bring_up(checkout, in_use=lambda venvs: running)  # noqa: E731
        route(machine, a_branch(machine, production, {"one.txt": "fixed\n"}, name="claude/one"), bring_up=waiting)
        asked_first = machine.hotfix_asked_for(production)

        route(machine, a_branch(machine, production, {"two.txt": "fixed\n"}, name="claude/two"), bring_up=waiting)
        running.clear()
        machine.bring_up(production)

        assert git("rev-parse", "HEAD^", cwd=production) == asked_first
        assert (production / "one.txt").is_file()
        assert (production / "two.txt").is_file()

    def test_a_hotfix_production_takes_meanwhile_is_built_on_and_not_taken_for_another(self, machine, production):
        running = [a_process("Example-Example.exe")]
        waiting = lambda checkout: machine.bring_up(checkout, in_use=lambda venvs: running)  # noqa: E731
        route(machine, a_branch(machine, production, {"one.txt": "fixed\n"}, name="claude/one"), bring_up=waiting)

        def production_takes_the_first_meanwhile(python, tests, place, pythonpath):
            running.clear()
            machine.bring_up(production)
            machine.bring_up(production)

        route(machine, a_branch(machine, production, {"two.txt": "fixed\n"}, name="claude/two"),
              checks=production_takes_the_first_meanwhile)

        assert (production / "one.txt").is_file()
        assert (production / "two.txt").is_file()

    def test_a_fix_that_needs_a_change_production_does_not_run_yet_goes_out_with_that_change(self, machine):
        production = machine.checkout(files={"pyproject.toml": HOTFIXABLE + PASSED_ONLY})
        (production / "state").mkdir()
        (production / "state" / "passed.txt").write_text(machine.head(production), encoding="utf-8")
        untested = machine.ship(production, {"untested.txt": "new\n"})
        worktree = a_branch(machine, production, {"untested.txt": "fixed\n"})

        said = route(machine, worktree)

        assert git("rev-parse", "HEAD^", cwd=production) == untested
        assert (production / "untested.txt").read_text(encoding="utf-8") == "fixed\n"
        assert "1 change that shipped" in said


class TestAFixInTheSharedCode:
    def test_it_reaches_every_app_whose_production_runs_that_code_as_a_version_of_its_own(self, machine):
        library = the_shared_code(machine)
        app = machine.checkout(files={"pyproject.toml": pins(funestra="0.1.1") + CHECKS})
        other = machine.checkout("other", files={"pyproject.toml": HOTFIXABLE})
        untouched = machine.head(other)
        worktree = a_branch(machine, library, {"engine.txt": "fixed\n"})
        authored = git("log", "-1", "--format=%ae %at", cwd=worktree)

        route(machine, worktree)

        assert "funestra@v0.1.1.1" in (app / "pyproject.toml").read_text(encoding="utf-8")
        assert git("show", "v0.1.1.1:engine.txt", cwd=library) == "fixed"
        assert f"Hotfix-of: {authored} in funestra" in git("log", "-1", "--format=%B", cwd=app)
        assert machine.head(other) == untouched

    def test_the_checks_run_with_that_version_ahead_of_the_one_installed(self, machine):
        library = the_shared_code(machine)
        app = machine.checkout(files={"pyproject.toml": pins(funestra="0.1.1") + CHECKS})
        worktree = a_branch(machine, library, {"engine.txt": "fixed\n", "tests/test_engine.py": "def test_it(): pass\n"})
        checks, sweeps = Checks(), Sweeps()

        route(machine, worktree, checks=checks, sweeps=sweeps)

        [(_, app_tests, _, pythonpath), (_, library_tests, library_place, also)] = checks.ran
        assert app_tests == ["tests/test_launch.py"]
        assert library_tests == ["tests/test_engine.py"]
        assert pythonpath == also == sweeps.ran[0][2] == [library_place]
        assert checks.heads[0] == [git("rev-parse", "v0.1.1.1^{commit}", cwd=library)]
        assert checks.ran[0][0] == sweeps.ran[0][0] == app / ".venv" / "Scripts" / "python.exe"

    def test_an_app_fix_that_needs_it_goes_out_with_it(self, machine):
        library = the_shared_code(machine)
        app = machine.checkout(files={"pyproject.toml": pins(funestra="0.1.1") + CHECKS})
        shared = a_branch(machine, library, {"engine.txt": "fixed\n"})
        worktree = a_branch(machine, app, {"uses_it.txt": "fixed\n"})

        route(machine, worktree, libraries=(shared,))

        assert (app / "uses_it.txt").is_file()
        assert "funestra@v0.1.1.1" in (app / "pyproject.toml").read_text(encoding="utf-8")

    def test_an_app_fix_that_takes_a_released_version_goes_out_with_that_version(self, machine):
        library = the_shared_code(machine)
        released = machine.release(library, "v0.1.2", machine.ship(library, {"engine.txt": "released\n"}))
        app = machine.checkout(files={"pyproject.toml": pins(funestra="0.1.1") + CHECKS})
        worktree = a_branch(machine, app, {"pyproject.toml": pins(funestra="0.1.2") + CHECKS})
        checks = Checks()

        route(machine, worktree, checks=checks)

        assert checks.heads[0] == [released]
        assert "funestra@v0.1.2" in (app / "pyproject.toml").read_text(encoding="utf-8")

    def test_a_fix_that_needs_what_changed_since_the_version_production_runs_goes_out_on_the_newest(self, machine):
        library = the_shared_code(machine)
        machine.release(library, "v0.1.2", machine.ship(library, {"engine.txt": "rewritten\n"}))
        app = machine.checkout(files={"pyproject.toml": pins(funestra="0.1.1") + CHECKS})
        worktree = a_branch(machine, library, {"engine.txt": "fixed\n"})

        said = route(machine, worktree)

        assert "funestra@v0.1.2.1" in (app / "pyproject.toml").read_text(encoding="utf-8")
        assert "1 change to funestra" in said

    def test_a_second_fix_to_a_version_production_runs_hotfixed_is_that_version_s_next_hotfix(self, machine):
        library = the_shared_code(machine)
        app = machine.checkout(files={"pyproject.toml": pins(funestra="0.1.1") + CHECKS})
        route(machine, a_branch(machine, library, {"engine.txt": "fixed\n"}, name="claude/one"))

        route(machine, a_branch(machine, library, {"other.txt": "fixed\n"}, name="claude/two"))

        assert "funestra@v0.1.1.2" in (app / "pyproject.toml").read_text(encoding="utf-8")
        assert git("show", "v0.1.1.2:engine.txt", cwd=library) == "fixed"

    def test_an_app_that_refuses_the_fix_leaves_the_others_to_take_it(self, machine):
        library = the_shared_code(machine)
        app = machine.checkout(files={"pyproject.toml": pins(funestra="0.1.1") + CHECKS})
        other = machine.checkout("other", files={"pyproject.toml": pins(funestra="0.1.1") + CHECKS})
        untouched = machine.head(other)

        def failing_for_the_other_app(python, tests, place, pythonpath):
            if place.name == "other":
                raise hotfix.Refused("tests/test_launch.py::test_it failed")

        with pytest.raises(hotfix.Refused, match=re.escape("production other refused it: tests/test_launch.py::test_it")):
            route(machine, a_branch(machine, library, {"engine.txt": "fixed\n"}), checks=failing_for_the_other_app)

        assert "funestra@v0.1.1.1" in (app / "pyproject.toml").read_text(encoding="utf-8")
        assert machine.head(other) == untouched

    def test_shared_code_the_app_does_not_run_is_refused(self, machine):
        library = the_shared_code(machine)
        app = machine.checkout(files={"pyproject.toml": HOTFIXABLE})
        shared = a_branch(machine, library, {"engine.txt": "fixed\n"})

        with pytest.raises(hotfix.Refused, match="does not run funestra"):
            route(machine, a_branch(machine, app, {"fix.txt": "fixed\n"}), libraries=(shared,))

        assert machine.hotfix_asked_for(app) is None

    def test_a_version_another_hotfix_took_meanwhile_is_never_moved(self, machine):
        library = the_shared_code(machine)
        app = machine.checkout(files={"pyproject.toml": pins(funestra="0.1.1") + CHECKS})
        released = git("rev-parse", "v0.1.1^{commit}", cwd=library)

        def another_hotfix_takes_it_meanwhile(python, tests, place, pythonpath):
            git("tag", "v0.1.1.1", released, cwd=library)

        with pytest.raises(hotfix.Refused, match=re.escape("funestra v0.1.1.1")):
            route(machine, a_branch(machine, library, {"engine.txt": "fixed\n"}),
                  checks=another_hotfix_takes_it_meanwhile)

        assert git("rev-parse", "v0.1.1.1^{commit}", cwd=library) == released
        assert machine.hotfix_asked_for(app) is None

    def test_a_version_this_computer_has_not_fetched_yet_is_fetched(self, machine):
        library = the_shared_code(machine)
        released = machine.release(library, "v0.1.2", machine.ship(library, {"engine.txt": "released\n"}))
        git("push", "-q", "origin", "v0.1.2", cwd=library)
        git("tag", "-d", "v0.1.2", cwd=library)
        app = machine.checkout(files={"pyproject.toml": pins(funestra="0.1.1") + CHECKS})
        checks = Checks()

        route(machine, a_branch(machine, app, {"pyproject.toml": pins(funestra="0.1.2") + CHECKS}), checks=checks)

        assert checks.heads[0] == [released]

    def test_a_version_found_neither_here_nor_on_github_is_refused(self, machine):
        the_shared_code(machine)
        app = machine.checkout(files={"pyproject.toml": pins(funestra="0.1.1") + CHECKS})

        with pytest.raises(hotfix.Refused, match=re.escape("funestra has no v0.1.9")):
            route(machine, a_branch(machine, app, {"pyproject.toml": pins(funestra="0.1.9") + CHECKS}))

        assert machine.hotfix_asked_for(app) is None

    def test_code_no_app_runs_is_refused(self, machine):
        library = the_shared_code(machine)
        machine.checkout(files={"pyproject.toml": HOTFIXABLE})
        worktree = a_branch(machine, library, {"engine.txt": "fixed\n"})

        with pytest.raises(hotfix.Refused, match="funestra"):
            route(machine, worktree)


class TestTheChecks:
    @staticmethod
    def a_checkout(tmp_path: Path, tests: dict[str, str]) -> Path:
        for name, text in tests.items():
            (tmp_path / "tests").mkdir(parents=True, exist_ok=True)
            (tmp_path / "tests" / name).write_text(text, encoding="utf-8")
        return tmp_path

    def test_checks_that_pass_let_the_hotfix_through(self, tmp_path):
        place = self.a_checkout(tmp_path, {"test_ok.py": "def test_ok(): pass\n"})

        hotfix.run_checks(Path(sys.executable), ["tests/test_ok.py"], place, [])

    def test_a_check_that_fails_refuses_the_hotfix_and_says_which(self, tmp_path):
        place = self.a_checkout(tmp_path, {"test_ok.py": "def test_ok(): pass\n",
                                           "test_bad.py": "def test_bad(): assert False\n"})

        with pytest.raises(hotfix.Refused, match="test_bad"):
            hotfix.run_checks(Path(sys.executable), ["tests/test_ok.py", "tests/test_bad.py"], place, [])

    def test_the_checks_import_the_shared_code_handed_to_them_first(self, tmp_path):
        place = self.a_checkout(tmp_path / "app", {"test_it.py": "import shared\ndef test_it(): assert shared.FIXED\n"})
        (tmp_path / "shared").mkdir()
        (tmp_path / "shared" / "shared.py").write_text("FIXED = True\n", encoding="utf-8")

        hotfix.run_checks(Path(sys.executable), ["tests/test_it.py"], place, [tmp_path / "shared"])

    def test_a_python_path_the_agent_s_shell_has_set_never_reaches_the_checks(self, tmp_path, monkeypatch):
        place = self.a_checkout(tmp_path / "app", {"test_it.py": "def test_it():\n    import shared\n"})
        (tmp_path / "shared").mkdir()
        (tmp_path / "shared" / "shared.py").write_text("FIXED = True\n", encoding="utf-8")
        monkeypatch.setenv("PYTHONPATH", str(tmp_path / "shared"))

        with pytest.raises(hotfix.Refused, match="No module named 'shared'"):
            hotfix.run_checks(Path(sys.executable), ["tests/test_it.py"], place, [])


class TestTheImportSweep:
    @staticmethod
    def an_app(place: Path, modules: dict[str, str]) -> Path:
        place.mkdir(parents=True)
        (place / "pyproject.toml").write_text(
            '[project]\nname = "toy-app"\n\n[tool.setuptools.packages.find]\ninclude = ["toy_app*"]\n', encoding="utf-8")
        for name, source in modules.items():
            (place / name).parent.mkdir(parents=True, exist_ok=True)
            (place / name).write_text(source, encoding="utf-8")
        return place

    def test_a_module_that_does_not_import_refuses_the_hotfix_and_says_which(self, tmp_path):
        place = self.an_app(tmp_path / "app", {"toy_app/__init__.py": "",
                                               "toy_app/broken.py": "import nowhere_to_be_found\n"})

        with pytest.raises(hotfix.Refused, match=re.escape("toy_app.broken did not import")):
            hotfix.run_sweep(Path(sys.executable), place, [])

    def test_an_app_whose_every_module_imports_lets_the_hotfix_through(self, tmp_path):
        place = self.an_app(tmp_path / "app", {"toy_app/__init__.py": "", "toy_app/alpha.py": "ALPHA = 1\n"})

        hotfix.run_sweep(Path(sys.executable), place, [])

    def test_the_sweep_imports_the_shared_code_handed_to_it_first(self, tmp_path):
        place = self.an_app(tmp_path / "app", {"toy_app/__init__.py": "from shared import FIXED\n"})
        (tmp_path / "shared").mkdir()
        (tmp_path / "shared" / "shared.py").write_text("FIXED = True\n", encoding="utf-8")

        hotfix.run_sweep(Path(sys.executable), place, [tmp_path / "shared"])


class TestTheCommandLine:
    def test_a_refusal_is_said_and_ends_the_command_in_failure(self, machine, production, monkeypatch, capsys,
                                                               tmp_path):
        worktree = a_branch(machine, production, {"fix.txt": "fixed\n"})
        (worktree / "fix.txt").write_text("fixed again\n", encoding="utf-8")
        monkeypatch.chdir(worktree)

        assert hotfix.main([], state=tmp_path / "state") == 1
        said = capsys.readouterr().out
        assert said.startswith("refused: ")
        assert "has uncommitted changes" in said

    def test_each_worktree_named_with_with_goes_out_with_the_fix(self, monkeypatch, tmp_path):
        handed = {}
        monkeypatch.setattr(hotfix, "hotfix", lambda worktree, **options: handed.update(options) or "done")

        assert hotfix.main(["--with", "one", "--with", "two"], state=tmp_path) == 0
        assert handed["libraries"] == [Path("one"), Path("two")]

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

    def test_a_fix_whose_modules_do_not_import_never_reaches_production(self, machine, production):
        worktree = a_branch(machine, production, {"fix.txt": "fixed\n"})

        with pytest.raises(hotfix.Refused, match="did not import"):
            route(machine, worktree, sweeps=Sweeps(failing=True))

        assert machine.hotfix_asked_for(production) is None

    def test_a_hotfix_production_did_not_take_is_asked_for_no_longer(self, machine, production):
        worktree = a_branch(machine, production, {"fix.txt": "fixed\n"})

        with pytest.raises(hotfix.Refused, match="pip said no"):
            route(machine, worktree, bring_up=lambda checkout: Outcome("failed: pip said no", 0.0, True))

        assert machine.hotfix_asked_for(production) is None

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

        def another_session_asks_meanwhile(python, tests, place, pythonpath):
            git("update-ref", "refs/haglio/hotfix", theirs, cwd=production)

        with pytest.raises(hotfix.Refused, match="another hotfix"):
            route(machine, worktree, checks=another_session_asks_meanwhile)

        assert machine.hotfix_asked_for(production) == theirs

    def test_a_repo_whose_production_names_no_checks_and_that_no_app_runs_is_refused(self, machine):
        production = machine.checkout()
        worktree = a_branch(machine, production, {"fix.txt": "fixed\n"})

        with pytest.raises(hotfix.Refused, match=r"\[tool\.haglio\.hotfix\]"):
            route(machine, worktree)

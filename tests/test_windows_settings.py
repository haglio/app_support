from __future__ import annotations

import dataclasses
import os
import sys
from pathlib import Path

import pytest

from app_support import scheduled_tasks, windows_settings
from app_support.win32 import read_shortcut, write_shortcut
from app_support.windows_settings import (
    ShortcutSpec,
    TaskSpec,
    WindowsSettingsError,
    declared,
)

LAUNCHERS = """
[tool.haglio.launchers."launch_example.vbs"]
app = "Example"
run = "-m example"
"""

SHORTCUT = """
[tool.haglio.shortcuts."Example"]
launcher = "launch_example.vbs"
icon = "example.ico"
app-id = "Example.App"
places = ["taskbar", "checkout"]
"""

TASK = """
[tool.haglio.scheduled-tasks."Example Tray"]
launcher = "launch_example.vbs"
every-minutes = 2
"""


def _checkout(parent: Path, specs: str, name: str = "example") -> Path:
    checkout = parent / name
    checkout.mkdir(parents=True, exist_ok=True)
    (checkout / "pyproject.toml").write_text(
        f'[project]\nname = "{name}"\n' + LAUNCHERS + specs, encoding="utf-8")
    return checkout


class TestTheDeclarations:
    def test_a_checkout_declares_its_shortcuts_in_its_pyproject(self, tmp_path: Path):
        (shortcut,) = declared(_checkout(tmp_path, SHORTCUT)).shortcuts

        assert shortcut == ShortcutSpec(name="Example", launcher="launch_example.vbs",
                                        icon="example.ico", app_id="Example.App",
                                        places=("taskbar", "checkout"))

    def test_a_checkout_declares_its_scheduled_tasks_in_its_pyproject(self, tmp_path: Path):
        (task,) = declared(_checkout(tmp_path, TASK)).scheduled_tasks

        assert task == TaskSpec(name="Example Tray", launcher="launch_example.vbs", every_minutes=2)

    def test_a_checkout_that_declares_neither_relies_on_nothing(self, tmp_path: Path):
        declarations = declared(_checkout(tmp_path, ""))

        assert (declarations.shortcuts, declarations.scheduled_tasks) == ((), ())

    def test_a_misspelled_key_is_refused_rather_than_ignored(self, tmp_path: Path):
        with pytest.raises(WindowsSettingsError, match="app_id"):
            declared(_checkout(tmp_path, SHORTCUT.replace("app-id", "app_id")))

    @pytest.mark.parametrize("key", ["launcher", "icon", "app-id", "places"])
    def test_a_shortcut_is_refused_without_each_of_its_keys(self, tmp_path: Path, key: str):
        without = "\n".join(line for line in SHORTCUT.splitlines()
                            if not line.startswith(f"{key} "))

        with pytest.raises(WindowsSettingsError, match=key):
            declared(_checkout(tmp_path, without))

    @pytest.mark.parametrize("key", ["launcher", "every-minutes"])
    def test_a_task_is_refused_without_each_of_its_keys(self, tmp_path: Path, key: str):
        without = "\n".join(line for line in TASK.splitlines() if not line.startswith(f"{key} "))

        with pytest.raises(WindowsSettingsError, match=key):
            declared(_checkout(tmp_path, without))

    @pytest.mark.parametrize("specs", [SHORTCUT, TASK], ids=["shortcut", "task"])
    def test_what_starts_is_one_of_this_checkouts_launchers(self, tmp_path: Path, specs: str):
        with pytest.raises(WindowsSettingsError, match=r"launch_other.vbs"):
            declared(_checkout(tmp_path, specs.replace("launch_example.vbs", "launch_other.vbs")))

    def test_a_shortcut_is_kept_only_where_windows_keeps_shortcuts(self, tmp_path: Path):
        with pytest.raises(WindowsSettingsError, match="desktop"):
            declared(_checkout(tmp_path, SHORTCUT.replace('"taskbar"', '"desktop"')))

    def test_a_shortcut_kept_nowhere_is_refused(self, tmp_path: Path):
        with pytest.raises(WindowsSettingsError, match="places"):
            declared(_checkout(tmp_path, SHORTCUT.replace('["taskbar", "checkout"]', "[]")))

    @pytest.mark.parametrize("every", ["0", '"2"', "1.5", "true"])
    def test_a_task_repeats_every_whole_minute_or_more(self, tmp_path: Path, every: str):
        with pytest.raises(WindowsSettingsError, match="every-minutes"):
            declared(_checkout(tmp_path, TASK.replace("every-minutes = 2", f"every-minutes = {every}")))

    @pytest.mark.parametrize("name", ["Ex/ample", "Ex\\\\ample", "Ex:ample", "Ex?ample", ""])
    def test_a_name_windows_cannot_give_a_file_is_refused(self, tmp_path: Path, name: str):
        with pytest.raises(WindowsSettingsError):
            declared(_checkout(tmp_path, SHORTCUT.replace('"Example"', f'"{name}"')))

    @pytest.mark.parametrize("icon", ["..\\\\example.ico", "C:\\\\example.ico"])
    def test_an_icon_outside_the_checkout_is_refused(self, tmp_path: Path, icon: str):
        with pytest.raises(WindowsSettingsError, match="icon"):
            declared(_checkout(tmp_path, SHORTCUT.replace('"example.ico"', f'"{icon}"')))

    @pytest.mark.parametrize("app_id", ['""', "3"])
    def test_a_shortcut_carries_an_identity_its_app_can_claim(self, tmp_path: Path, app_id: str):
        with pytest.raises(WindowsSettingsError, match="app-id"):
            declared(_checkout(tmp_path, SHORTCUT.replace('"Example.App"', app_id)))


WSCRIPT = Path(os.environ.get("SYSTEMROOT", r"C:\Windows")) / "System32" / "wscript.exe"


class TestWhatADeclarationMakes:
    def test_a_shortcut_starts_its_launcher_hidden_in_its_checkout(self, tmp_path: Path):
        checkout = _checkout(tmp_path, SHORTCUT)
        (spec,) = declared(checkout).shortcuts

        shortcut = windows_settings.shortcut_for(checkout, spec)

        assert shortcut.target == str(WSCRIPT)
        assert shortcut.arguments == f'"{checkout / "launch_example.vbs"}"'
        assert shortcut.working_directory == str(checkout)
        assert shortcut.icon == str(checkout / "example.ico")
        assert shortcut.app_id == "Example.App"

    def test_a_shortcut_says_which_checkouts_list_keeps_it(self, tmp_path: Path):
        checkout = _checkout(tmp_path, SHORTCUT)
        (spec,) = declared(checkout).shortcuts

        description = windows_settings.shortcut_for(checkout, spec).description

        assert description == "Kept by app_support.windows_settings from example\\pyproject.toml"
        assert windows_settings.kept_by(description) == "example"

    def test_a_description_anyone_else_wrote_names_no_checkout(self):
        assert windows_settings.kept_by("Launch the tray icon") is None
        assert windows_settings.kept_by("") is None

    def test_a_task_lives_in_the_familys_folder_and_starts_its_launcher(self, tmp_path: Path):
        checkout = _checkout(tmp_path, TASK)
        (spec,) = declared(checkout).scheduled_tasks

        task = windows_settings.task_for(checkout, spec)

        assert task.path == "\\Haglio\\Example Tray"
        assert task.command == str(WSCRIPT)
        assert task.arguments == f'"{checkout / "launch_example.vbs"}"'
        assert task.working_directory == str(checkout)
        assert task.every_minutes == 2
        assert windows_settings.kept_by(task.description) == "example"


class _TaskScheduler:
    """Task Scheduler's command-line tool, holding its tasks in a dict."""

    def __init__(self, tasks: dict[str, str] | None = None) -> None:
        self.tasks = dict(tasks or {})

    def __call__(self, *arguments: str) -> str:
        match arguments:
            case ("/query", "/fo", "csv", "/nh"):
                return "".join(f'"{path}","N/A","Ready"\n' for path in self.tasks)
            case ("/query", "/tn", path, "/xml"):
                return self.tasks[path]
            case ("/create", "/tn", path, "/xml", task_file, "/f"):
                self.tasks[path] = Path(task_file).read_text(encoding="utf-16")
            case ("/delete", "/tn", path, "/f"):
                del self.tasks[path]
            case _:
                raise AssertionError(f"not a call this module makes: {arguments}")
        return ""


@pytest.fixture
def places(tmp_path: Path, monkeypatch) -> dict[str, Path]:
    appdata = tmp_path / "appdata"
    monkeypatch.setenv("APPDATA", str(appdata))
    programs = appdata / "Microsoft" / "Windows" / "Start Menu" / "Programs"
    found = {
        "taskbar": appdata / "Microsoft" / "Internet Explorer" / "Quick Launch" / "User Pinned"
        / "TaskBar",
        "start-menu": programs,
        "startup": programs / "Startup",
    }
    for folder in found.values():
        folder.mkdir(parents=True)
    return found


def _made(found: list[windows_settings.Change]) -> list[windows_settings.Change]:
    for change in found:
        change.make()
    return found


KEPT_BY_EXAMPLE = "Kept by app_support.windows_settings from example\\pyproject.toml"


@pytest.mark.skipif(sys.platform != "win32", reason="shortcuts: only Windows can say")
class TestMakingTheMachineMatch:
    def test_a_machine_that_matches_every_list_is_left_as_it_is(self, tmp_path: Path, places):
        workspace = tmp_path / "workspace"
        _checkout(workspace, SHORTCUT + TASK)
        scheduler = _TaskScheduler()
        _made(windows_settings.changes(workspace, run=scheduler))

        assert windows_settings.changes(workspace, run=scheduler) == []

    def test_the_shortcut_kept_in_its_checkout_is_added_when_missing(self, tmp_path: Path, places):
        checkout = _checkout(tmp_path / "workspace", SHORTCUT)

        (change,) = _made(windows_settings.changes(tmp_path / "workspace", run=_TaskScheduler()))

        assert change.what == f"add {checkout / 'Example.lnk'}"
        (spec,) = declared(checkout).shortcuts
        assert windows_settings.what_differs(read_shortcut(str(checkout / "Example.lnk")),
                                             windows_settings.shortcut_for(checkout, spec)) == []

    @pytest.mark.parametrize("place", ["taskbar", "start-menu", "startup"])
    def test_a_shortcut_the_user_decides_on_is_never_added(self, tmp_path: Path, places, place):
        workspace = tmp_path / "workspace"
        _checkout(workspace, SHORTCUT.replace('["taskbar", "checkout"]', f'["{place}"]'))

        assert windows_settings.changes(workspace, run=_TaskScheduler()) == []

    def test_a_pin_that_starts_an_old_checkout_is_pointed_at_this_one(self, tmp_path: Path, places):
        checkout = _checkout(tmp_path / "workspace", SHORTCUT.replace(', "checkout"', ""))
        pin = places["taskbar"] / "Example.lnk"
        (spec,) = declared(checkout).shortcuts
        wanted = windows_settings.shortcut_for(checkout, spec)
        write_shortcut(str(pin), **{**dataclasses.asdict(wanted),
                                    "arguments": '"C:\\old\\launch_example.vbs"'})

        (change,) = _made(windows_settings.changes(tmp_path / "workspace", run=_TaskScheduler()))

        assert change.what == (f'fix {pin}: arguments: "C:\\old\\launch_example.vbs" instead of'
                               f' "{checkout / "launch_example.vbs"}"')
        assert read_shortcut(str(pin)).arguments == f'"{checkout / "launch_example.vbs"}"'

    def test_case_alone_is_not_something_to_fix(self, tmp_path: Path, places):
        checkout = _checkout(tmp_path / "workspace", SHORTCUT.replace(', "checkout"', ""))
        (spec,) = declared(checkout).shortcuts
        wanted = windows_settings.shortcut_for(checkout, spec)
        write_shortcut(str(places["taskbar"] / "Example.lnk"),
                       **{**dataclasses.asdict(wanted), "arguments": wanted.arguments.upper()})

        assert windows_settings.changes(tmp_path / "workspace", run=_TaskScheduler()) == []

    @pytest.mark.parametrize("place", ["start-menu", "startup"])
    def test_a_shortcut_its_list_no_longer_has_is_removed(self, tmp_path: Path, places, place):
        workspace = tmp_path / "workspace"
        _checkout(workspace, "")
        retired = places[place] / "Retired.lnk"
        write_shortcut(str(retired), target=str(WSCRIPT), description=KEPT_BY_EXAMPLE)

        (change,) = _made(windows_settings.changes(workspace, run=_TaskScheduler()))

        assert change.what == f"remove {retired}: example no longer lists it"
        assert not retired.exists()

    def test_a_shortcut_in_a_checkout_its_list_no_longer_has_is_removed(
        self, tmp_path: Path, places,
    ):
        checkout = _checkout(tmp_path / "workspace", "")
        retired = checkout / "Retired.lnk"
        write_shortcut(str(retired), target=str(WSCRIPT), description=KEPT_BY_EXAMPLE)

        _made(windows_settings.changes(tmp_path / "workspace", run=_TaskScheduler()))

        assert not retired.exists()

    def test_a_shortcut_someone_else_made_is_left_alone(self, tmp_path: Path, places):
        workspace = tmp_path / "workspace"
        _checkout(workspace, "")
        write_shortcut(str(places["startup"] / "Theirs.lnk"), target=str(WSCRIPT),
                       description="Starts something of someone else's")

        assert windows_settings.changes(workspace, run=_TaskScheduler()) == []

    def test_a_shortcut_whose_checkout_is_not_here_to_ask_is_left_alone(
        self, tmp_path: Path, places,
    ):
        workspace = tmp_path / "workspace"
        _checkout(workspace, "")
        write_shortcut(str(places["startup"] / "Elsewhere.lnk"), target=str(WSCRIPT),
                       description=KEPT_BY_EXAMPLE.replace("example", "moved"))

        assert windows_settings.changes(workspace, run=_TaskScheduler()) == []

    def test_a_pin_its_list_no_longer_has_is_for_a_person_to_unpin(self, tmp_path: Path, places):
        workspace = tmp_path / "workspace"
        _checkout(workspace, "")
        write_shortcut(str(places["taskbar"] / "Retired.lnk"), target=str(WSCRIPT),
                       description=KEPT_BY_EXAMPLE)

        (change,) = windows_settings.changes(workspace, run=_TaskScheduler())

        assert change.what == "unpin Retired from the taskbar: example no longer lists it"
        assert change.make is None

    def test_a_missing_task_is_registered(self, tmp_path: Path, places):
        workspace = tmp_path / "workspace"
        _checkout(workspace, TASK)
        scheduler = _TaskScheduler()

        (change,) = _made(windows_settings.changes(workspace, run=scheduler))

        assert change.what == "register the scheduled task \\Haglio\\Example Tray"
        assert list(scheduler.tasks) == ["\\Haglio\\Example Tray"]

    def test_a_task_that_starts_an_old_checkout_is_registered_again(self, tmp_path: Path, places):
        checkout = _checkout(tmp_path / "workspace", TASK)
        (spec,) = declared(checkout).scheduled_tasks
        old = dataclasses.replace(windows_settings.task_for(checkout, spec),
                                  arguments='"C:\\old\\launch_example.vbs"')
        scheduler = _TaskScheduler({"\\Haglio\\Example Tray": scheduled_tasks.render(
            old, user=scheduled_tasks.this_user())})

        (change,) = _made(windows_settings.changes(tmp_path / "workspace", run=scheduler))

        assert change.what == (
            "register the scheduled task \\Haglio\\Example Tray again: Actions/Exec/Arguments: "
            f'"C:\\old\\launch_example.vbs" instead of "{checkout / "launch_example.vbs"}"')
        assert windows_settings.changes(tmp_path / "workspace", run=scheduler) == []

    def test_a_task_its_list_no_longer_has_is_deleted(self, tmp_path: Path, places):
        checkout = _checkout(tmp_path / "workspace", TASK)
        (spec,) = declared(checkout).scheduled_tasks
        retired = dataclasses.replace(windows_settings.task_for(checkout, spec),
                                      path="\\Haglio\\Retired")
        scheduler = _TaskScheduler({"\\Haglio\\Retired": scheduled_tasks.render(
            retired, user=scheduled_tasks.this_user())})
        _checkout(tmp_path / "workspace", "")

        (change,) = _made(windows_settings.changes(tmp_path / "workspace", run=scheduler))

        assert change.what == "delete the scheduled task \\Haglio\\Retired: example no longer lists it"
        assert scheduler.tasks == {}

    def test_a_task_whose_checkout_is_not_here_to_ask_is_left_alone(self, tmp_path: Path, places):
        checkout = _checkout(tmp_path / "moved", TASK)
        (spec,) = declared(checkout).scheduled_tasks
        scheduler = _TaskScheduler({"\\Haglio\\Example Tray": scheduled_tasks.render(
            windows_settings.task_for(checkout, spec), user=scheduled_tasks.this_user())})
        _checkout(tmp_path / "workspace", "", name="other")

        assert windows_settings.changes(tmp_path / "workspace", run=scheduler) == []

    def test_two_lists_keeping_one_shortcut_in_one_place_are_refused(self, tmp_path: Path, places):
        workspace = tmp_path / "workspace"
        startup = SHORTCUT.replace('["taskbar", "checkout"]', '["startup"]')
        _checkout(workspace, startup, name="first")
        _checkout(workspace, startup, name="second")

        with pytest.raises(WindowsSettingsError, match=r"first.*second"):
            windows_settings.changes(workspace, run=_TaskScheduler())

    def test_two_lists_keeping_one_task_are_refused(self, tmp_path: Path, places):
        workspace = tmp_path / "workspace"
        _checkout(workspace, TASK, name="first")
        _checkout(workspace, TASK, name="second")

        with pytest.raises(WindowsSettingsError, match=r"first.*second"):
            windows_settings.changes(workspace, run=_TaskScheduler())

    def test_a_list_that_cannot_be_read_stops_every_change(self, tmp_path: Path, places):
        workspace = tmp_path / "workspace"
        _checkout(workspace, TASK, name="readable")
        _checkout(workspace, SHORTCUT.replace("app-id", "app_id"), name="broken")

        with pytest.raises(WindowsSettingsError, match="broken"):
            windows_settings.changes(workspace, run=_TaskScheduler())


@pytest.mark.skipif(sys.platform != "win32", reason="shortcuts: only Windows can say")
class TestAnAppWritingItsOwnShortcut:
    def test_it_writes_the_shortcut_its_list_keeps_there(self, tmp_path: Path, places):
        checkout = _checkout(tmp_path, SHORTCUT.replace('"checkout"]', '"startup"]'))
        (spec,) = declared(checkout).shortcuts

        written = windows_settings.write_shortcut(checkout, "Example", "startup")

        assert written == windows_settings.shortcut_file(checkout, "Example", "startup")
        assert written == places["startup"] / "Example.lnk"
        assert windows_settings.what_differs(
            read_shortcut(str(written)), windows_settings.shortcut_for(checkout, spec)) == []

    @pytest.mark.parametrize(("name", "place"), [("Example", "startup"), ("Other", "taskbar")])
    def test_a_shortcut_its_list_does_not_keep_there_is_refused(
        self, tmp_path: Path, places, name: str, place: str,
    ):
        checkout = _checkout(tmp_path, SHORTCUT)

        with pytest.raises(WindowsSettingsError, match=name):
            windows_settings.write_shortcut(checkout, name, place)

        assert not windows_settings.shortcut_file(checkout, name, place).exists()

    @pytest.mark.parametrize("place", ["taskbar", "start-menu", "startup"])
    def test_a_shortcut_windows_keeps_is_named_for_its_place_alone(
        self, tmp_path: Path, places, place: str,
    ):
        assert (windows_settings.shortcut_file(tmp_path / "anywhere", "Example", place)
                == places[place] / "Example.lnk")

    def test_a_shortcut_kept_in_the_checkout_is_named_for_the_checkout(self, tmp_path: Path):
        assert (windows_settings.shortcut_file(tmp_path, "Example", "checkout")
                == tmp_path / "Example.lnk")


@pytest.mark.skipif(sys.platform != "win32", reason="shortcuts: only Windows can say")
class TestTheCommandLine:
    def test_it_names_what_differs_and_then_makes_it_match(self, tmp_path: Path, places, capsys):
        workspace = tmp_path / "workspace"
        checkout = _checkout(workspace, SHORTCUT + TASK)
        scheduler = _TaskScheduler()
        arguments = ["--workspace", str(workspace)]

        assert windows_settings.main(arguments, run=scheduler) == 1
        assert capsys.readouterr().out.splitlines() == [
            f"add {checkout / 'Example.lnk'}",
            "register the scheduled task \\Haglio\\Example Tray",
        ]

        assert windows_settings.main([*arguments, "--write"], run=scheduler) == 0
        assert capsys.readouterr().out.splitlines() == [
            f"done: add {checkout / 'Example.lnk'}",
            "done: register the scheduled task \\Haglio\\Example Tray",
        ]

        assert windows_settings.main(arguments, run=scheduler) == 0
        assert capsys.readouterr().out == ""

    def test_what_only_a_person_can_do_is_named_for_one(self, tmp_path: Path, places, capsys):
        workspace = tmp_path / "workspace"
        _checkout(workspace, "")
        write_shortcut(str(places["taskbar"] / "Retired.lnk"), target=str(WSCRIPT),
                       description=KEPT_BY_EXAMPLE)

        assert windows_settings.main(["--workspace", str(workspace), "--write"],
                                     run=_TaskScheduler()) == 1
        assert capsys.readouterr().out.splitlines() == [
            "needs a person: unpin Retired from the taskbar: example no longer lists it"]

    def test_a_refusal_is_named_and_the_rest_are_still_made(self, tmp_path: Path, places, capsys):
        workspace = tmp_path / "workspace"
        checkout = _checkout(workspace, SHORTCUT + TASK)

        def refusing(*arguments: str) -> str:
            if arguments[0] == "/create":
                raise OSError("ERROR: Access is denied.")
            return _TaskScheduler()(*arguments)

        assert windows_settings.main(["--workspace", str(workspace), "--write"],
                                     run=refusing) == 1
        assert capsys.readouterr().out.splitlines() == [
            f"done: add {checkout / 'Example.lnk'}",
            "failed: register the scheduled task \\Haglio\\Example Tray: ERROR: Access is denied.",
        ]


class TestACheckoutsOwnCheck:
    def test_a_list_whose_icons_and_launchers_are_there_passes(self, tmp_path: Path):
        checkout = _checkout(tmp_path, SHORTCUT + TASK)
        (checkout / "example.ico").write_bytes(b"")
        (checkout / "launch_example.vbs").write_text("", encoding="ascii")

        windows_settings.assert_listed_settings_can_be_made(checkout)

    def test_an_icon_that_is_not_there_is_named(self, tmp_path: Path):
        checkout = _checkout(tmp_path, SHORTCUT)
        (checkout / "launch_example.vbs").write_text("", encoding="ascii")

        with pytest.raises(AssertionError, match=r"example\.ico"):
            windows_settings.assert_listed_settings_can_be_made(checkout)

    @pytest.mark.parametrize("specs", [SHORTCUT, TASK], ids=["shortcut", "task"])
    def test_a_launcher_that_is_not_rendered_is_named(self, tmp_path: Path, specs: str):
        checkout = _checkout(tmp_path, specs)
        (checkout / "example.ico").write_bytes(b"")

        with pytest.raises(AssertionError, match=r"launch_example\.vbs"):
            windows_settings.assert_listed_settings_can_be_made(checkout)


class TestWhereTheCheckoutsAre:
    def _module_in(self, checkout: Path) -> Path:
        (checkout / "app_support").mkdir(parents=True)
        (checkout / "pyproject.toml").write_text("", encoding="utf-8")
        module = checkout / "app_support" / "windows_settings.py"
        module.write_text("", encoding="utf-8")
        return module

    def test_they_are_beside_the_checkout_this_runs_from(self, tmp_path: Path):
        module = self._module_in(tmp_path / "workspace" / "app_support")

        assert windows_settings.workspace_of(module) == tmp_path / "workspace"

    def test_from_a_worktree_they_are_beside_its_primary_checkout(self, tmp_path: Path):
        primary = tmp_path / "workspace" / "app_support"
        module = self._module_in(primary / ".claude" / "worktrees" / "some-branch")
        (primary / "pyproject.toml").write_text("", encoding="utf-8")

        assert windows_settings.workspace_of(module) == tmp_path / "workspace"

    def test_a_copy_installed_into_a_venv_has_to_be_told(self, tmp_path: Path):
        module = tmp_path / "venv" / "Lib" / "site-packages" / "app_support" / "windows_settings.py"
        module.parent.mkdir(parents=True)
        module.write_text("", encoding="utf-8")

        with pytest.raises(WindowsSettingsError, match="--workspace"):
            windows_settings.workspace_of(module)

"""The Windows settings each app relies on, declared in its own pyproject and
made true on this machine by one command.

    [tool.haglio.shortcuts."Example"]
    launcher = "launch_example.vbs"
    icon = "example.ico"
    app-id = "Example.App"
    places = ["taskbar", "checkout"]

    [tool.haglio.scheduled-tasks."Example Tray"]
    launcher = "launch_example.vbs"
    every-minutes = 2

``python -m app_support.windows_settings`` names what on this machine differs
from what the checkouts beside this one list; ``--write`` makes it match.
Windows lets no program pin to the taskbar, so a pin is only ever corrected, and
the copy kept in the checkout is the one to pin from.

Standard library only.
"""
from __future__ import annotations

import argparse
import contextlib
import dataclasses
import functools
import os
import re
import sys
import tomllib
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath

from app_support import launcher, scheduled_tasks, win32

PLACES = ("taskbar", "start-menu", "startup", "checkout")
TASK_FOLDER = "\\Haglio"

_ADDED_WHEN_MISSING = ("checkout",)
_SHORTCUT_KEYS = ("launcher", "icon", "app-id", "places")
_TASK_KEYS = ("launcher", "every-minutes")
_UNUSABLE_IN_A_FILE_NAME = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_KEPT_BY = re.compile(
    r"Kept by app_support\.windows_settings from (?P<checkout>[^\\]+)\\pyproject\.toml")


class WindowsSettingsError(ValueError):
    pass


@dataclass(frozen=True)
class ShortcutSpec:
    name: str
    launcher: str
    icon: str
    app_id: str
    places: tuple[str, ...]


@dataclass(frozen=True)
class TaskSpec:
    name: str
    launcher: str
    every_minutes: int


@dataclass(frozen=True)
class Declarations:
    shortcuts: tuple[ShortcutSpec, ...] = ()
    scheduled_tasks: tuple[TaskSpec, ...] = ()


def declared(checkout: Path) -> Declarations:
    document = tomllib.loads((Path(checkout) / "pyproject.toml").read_text(encoding="utf-8"))
    haglio = document.get("tool", {}).get("haglio", {})
    launchers = {found.file for found in launcher.launchers(checkout)}
    return Declarations(
        shortcuts=tuple(_shortcut(name, spec, launchers)
                        for name, spec in haglio.get("shortcuts", {}).items()),
        scheduled_tasks=tuple(_task(name, spec, launchers)
                              for name, spec in haglio.get("scheduled-tasks", {}).items()),
    )


def _shortcut(name: str, spec: dict, launchers: set[str]) -> ShortcutSpec:
    refuse = _refuser(f'[tool.haglio.shortcuts."{name}"]')
    _refuse_unusable_name(refuse, name)
    _refuse_other_keys(refuse, spec, _SHORTCUT_KEYS)
    icon = spec["icon"]
    if not isinstance(icon, str) or PureWindowsPath(icon).is_absolute() or ".." in PureWindowsPath(icon).parts:
        raise refuse(f"icon {icon!r} must be a file inside the checkout")
    places = spec["places"]
    if not isinstance(places, list) or not places:
        raise refuse(f"places must name one or more of {', '.join(PLACES)}")
    for place in places:
        if place not in PLACES:
            raise refuse(f"places names {place!r}, which is not one of {', '.join(PLACES)}")
    app_id = spec["app-id"]
    if not isinstance(app_id, str) or not app_id:
        raise refuse(f"app-id must be the identity the app claims, not {app_id!r}")
    return ShortcutSpec(name=name, launcher=_launcher(refuse, spec, launchers), icon=icon,
                        app_id=app_id, places=tuple(places))


def _task(name: str, spec: dict, launchers: set[str]) -> TaskSpec:
    refuse = _refuser(f'[tool.haglio.scheduled-tasks."{name}"]')
    _refuse_unusable_name(refuse, name)
    _refuse_other_keys(refuse, spec, _TASK_KEYS)
    every = spec["every-minutes"]
    if isinstance(every, bool) or not isinstance(every, int) or every < 1:
        raise refuse(f"every-minutes must be a whole number of minutes, not {every!r}")
    return TaskSpec(name=name, launcher=_launcher(refuse, spec, launchers), every_minutes=every)


def _refuser(table: str):
    def refuse(message: str) -> WindowsSettingsError:
        return WindowsSettingsError(f"{table}: {message}")
    return refuse


def _refuse_unusable_name(refuse, name: str) -> None:
    if not name.strip() or _UNUSABLE_IN_A_FILE_NAME.search(name):
        raise refuse("the name must be one Windows can give a file")


def _refuse_other_keys(refuse, spec: dict, keys: tuple[str, ...]) -> None:
    unknown = sorted(set(spec) - set(keys))
    if unknown:
        raise refuse(f"unknown key {', '.join(unknown)}")
    for key in keys:
        if key not in spec:
            raise refuse(f"{key} is required")


def _launcher(refuse, spec: dict, launchers: set[str]) -> str:
    if not isinstance(spec["launcher"], str) or spec["launcher"] not in launchers:
        raise refuse(f"launcher {spec['launcher']!r} is not one of this checkout's "
                     "[tool.haglio.launchers]")
    return spec["launcher"]


def shortcut_for(checkout: Path, spec: ShortcutSpec) -> win32.Shortcut:
    return win32.Shortcut(
        target=str(_wscript()),
        arguments=f'"{Path(checkout) / spec.launcher}"',
        working_directory=str(checkout),
        icon=str(Path(checkout) / spec.icon),
        description=_kept_by(checkout),
        app_id=spec.app_id,
    )


def task_for(checkout: Path, spec: TaskSpec) -> scheduled_tasks.RecurringTask:
    return scheduled_tasks.RecurringTask(
        path=f"{TASK_FOLDER}\\{spec.name}",
        description=_kept_by(checkout),
        command=str(_wscript()),
        arguments=f'"{Path(checkout) / spec.launcher}"',
        working_directory=str(checkout),
        every_minutes=spec.every_minutes,
    )


def _wscript() -> Path:
    return Path(os.environ.get("SYSTEMROOT", r"C:\Windows")) / "System32" / "wscript.exe"


def _kept_by(checkout: Path) -> str:
    return f"Kept by app_support.windows_settings from {Path(checkout).name}\\pyproject.toml"


def kept_by(description: str) -> str | None:
    """The checkout whose list put a shortcut or task where it is, or None
    when nothing this module wrote is there."""
    found = _KEPT_BY.fullmatch(description)
    return found["checkout"] if found else None


def shortcut_file(place: str, checkout: Path, name: str) -> Path:
    return (Path(checkout) if place == "checkout" else windows_folder(place)) / f"{name}.lnk"


def windows_folder(place: str) -> Path:
    if place == "taskbar":
        return win32.taskbar_pins()
    programs = (Path(os.environ.get("APPDATA", "")) / "Microsoft" / "Windows" / "Start Menu"
                / "Programs")
    return programs / "Startup" if place == "startup" else programs


def what_differs(found: win32.Shortcut, wanted: win32.Shortcut) -> list[str]:
    differences = []
    for field in dataclasses.fields(win32.Shortcut):
        have, want = getattr(found, field.name), getattr(wanted, field.name)
        if _comparable(field.name, have) != _comparable(field.name, want):
            differences.append(f"{field.name}: {_spelled(have)} instead of {_spelled(want)}")
    return differences


def _comparable(field: str, value):
    if field in ("target", "working_directory", "icon"):
        return os.path.normcase(value)
    if field == "arguments":
        return value.casefold()
    return value


def _spelled(value) -> str:
    return "nothing" if value in (None, "") else str(value)


@dataclass(frozen=True)
class Change:
    what: str
    make: Callable[[], None] | None = None


def changes(workspace: Path, *, run=scheduled_tasks.schtasks) -> list[Change]:
    """What would make this machine hold what every checkout in *workspace* lists.
    A change with nothing to make it is one only a person can make."""
    checkouts = _lists(workspace)
    return _shortcut_changes(checkouts) + _task_changes(checkouts, run)


def _lists(workspace: Path) -> dict[str, tuple[Path, Declarations]]:
    found = {}
    for checkout in sorted(Path(workspace).iterdir()):
        if checkout.name.startswith(".") or not (checkout / "pyproject.toml").is_file():
            continue
        try:
            found[checkout.name] = (checkout, declared(checkout))
        except ValueError as unreadable:
            raise WindowsSettingsError(f"{checkout.name}: {unreadable}") from unreadable
    return found


def _shortcut_changes(checkouts: dict[str, tuple[Path, Declarations]]) -> list[Change]:
    wanted: dict[str, tuple[Path, win32.Shortcut, str, str]] = {}
    for owner, (checkout, declarations) in checkouts.items():
        for spec in declarations.shortcuts:
            shortcut = shortcut_for(checkout, spec)
            for place in spec.places:
                path = shortcut_file(place, checkout, spec.name)
                key = os.path.normcase(path)
                if key in wanted:
                    raise WindowsSettingsError(
                        f"{path} is listed by both {wanted[key][3]} and {owner}")
                wanted[key] = (path, shortcut, place, owner)
    found = [change for path, shortcut, place, _owner in wanted.values()
             for change in _shortcut_change(path, shortcut, place)]
    swept = [(place, windows_folder(place)) for place in PLACES if place != "checkout"]
    swept += [("checkout", checkout) for checkout, _declarations in checkouts.values()]
    for place, swept_folder in swept:
        for lnk in sorted(swept_folder.glob("*.lnk")):
            if os.path.normcase(lnk) in wanted:
                continue
            with contextlib.suppress(OSError):
                owner = kept_by(win32.read_shortcut(str(lnk)).description)
                if owner in checkouts:
                    found.append(_retirement(lnk, place, owner))
    return found


def _shortcut_change(path: Path, shortcut: win32.Shortcut, place: str) -> list[Change]:
    write = functools.partial(_write, path, shortcut)
    if not path.is_file():
        return [Change(f"add {path}", write)] if place in _ADDED_WHEN_MISSING else []
    try:
        differences = what_differs(win32.read_shortcut(str(path)), shortcut)
    except OSError:
        differences = ["Windows cannot read it as a shortcut"]
    return [Change(f"fix {path}: {'; '.join(differences)}", write)] if differences else []


def _retirement(lnk: Path, place: str, owner: str) -> Change:
    if place == "taskbar":
        return Change(f"unpin {lnk.stem} from the taskbar: {owner} no longer lists it")
    return Change(f"remove {lnk}: {owner} no longer lists it", lnk.unlink)


def _write(path: Path, shortcut: win32.Shortcut) -> None:
    win32.write_shortcut(str(path), **dataclasses.asdict(shortcut))


def _task_changes(checkouts: dict[str, tuple[Path, Declarations]], run) -> list[Change]:
    wanted: dict[str, tuple[scheduled_tasks.RecurringTask, str]] = {}
    for owner, (checkout, declarations) in checkouts.items():
        for spec in declarations.scheduled_tasks:
            task = task_for(checkout, spec)
            if task.path.casefold() in wanted:
                raise WindowsSettingsError(f"the scheduled task {task.path} is listed by both "
                                           f"{wanted[task.path.casefold()][1]} and {owner}")
            wanted[task.path.casefold()] = (task, owner)
    registered = {path.casefold(): path for path in scheduled_tasks.tasks_in(TASK_FOLDER, run=run)}
    user = scheduled_tasks.this_user()
    found = []
    for key, (task, _owner) in wanted.items():
        xml = scheduled_tasks.render(task, user=user)
        register = functools.partial(scheduled_tasks.register, task.path, xml, run=run)
        if key not in registered:
            found.append(Change(f"register the scheduled task {task.path}", register))
            continue
        differences = scheduled_tasks.what_differs(
            xml, scheduled_tasks.registered(registered[key], run=run))
        if differences:
            found.append(Change(f"register the scheduled task {task.path} again: "
                                + "; ".join(differences), register))
    for key, path in registered.items():
        if key in wanted:
            continue
        owner = kept_by(scheduled_tasks.description_of(scheduled_tasks.registered(path, run=run)))
        if owner in checkouts:
            found.append(Change(f"delete the scheduled task {path}: {owner} no longer lists it",
                                functools.partial(scheduled_tasks.delete, path, run=run)))
    return found


def shortcut_path(checkout: Path, name: str, place: str) -> Path:
    return shortcut_file(place, checkout, _listed(checkout, name, place).name)


def write_shortcut(checkout: Path, name: str, place: str) -> Path:
    """Put the shortcut *checkout*'s list keeps in *place* there now, for the
    app whose own setting decides whether it is there at all."""
    spec = _listed(checkout, name, place)
    path = shortcut_file(place, checkout, spec.name)
    _write(path, shortcut_for(checkout, spec))
    return path


def assert_listed_settings_can_be_made(checkout: Path) -> None:
    __tracebackhide__ = True
    declarations = declared(checkout)
    needed = [spec.icon for spec in declarations.shortcuts]
    needed += [spec.launcher for spec in (*declarations.shortcuts, *declarations.scheduled_tasks)]
    missing = sorted({name for name in needed if not (Path(checkout) / name).is_file()})
    assert not missing, (
        "what this checkout's Windows settings start or show is not in it:\n  "
        + "\n  ".join(missing))


def _listed(checkout: Path, name: str, place: str) -> ShortcutSpec:
    for spec in declared(checkout).shortcuts:
        if spec.name == name and place in spec.places:
            return spec
    raise WindowsSettingsError(f"{Path(checkout).name}'s list keeps no shortcut {name} in {place}")


def workspace_of(module_file: Path) -> Path:
    checkout = Path(module_file).resolve().parents[1]
    if checkout.parent.name == "worktrees" and checkout.parent.parent.name == ".claude":
        checkout = checkout.parents[2]
    if not (checkout / "pyproject.toml").is_file():
        raise WindowsSettingsError(
            f"{module_file} is not in a checkout, so the checkouts beside it cannot be found: "
            "name the folder that holds them with --workspace")
    return checkout.parent


def main(argv: list[str] | None = None, *, run=scheduled_tasks.schtasks) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m app_support.windows_settings",
        description="Name what on this machine differs from the Windows settings every "
                    "checkout lists, or make it match.")
    parser.add_argument("--write", action="store_true",
                        help="make this machine match, rather than only naming what differs")
    parser.add_argument("--workspace", type=Path, default=None,
                        help="the folder holding the checkouts, if not the one holding this one")
    options = parser.parse_args(argv)
    found = changes(options.workspace or workspace_of(Path(__file__)), run=run)
    if not options.write:
        for change in found:
            print(change.what)
        return 1 if found else 0
    complete = True
    for change in found:
        if change.make is None:
            print(f"needs a person: {change.what}")
            complete = False
            continue
        try:
            change.make()
        except OSError as refusal:
            print(f"failed: {change.what}: {refusal}")
            complete = False
        else:
            print(f"done: {change.what}")
    return 0 if complete else 1


if __name__ == "__main__":
    sys.exit(main())

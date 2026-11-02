from __future__ import annotations

import re
from collections.abc import Iterable
from pathlib import Path, PureWindowsPath

from app_support import production_update, windows_settings
from app_support.launcher import Launcher, dry_run, launchers

_MODULE = re.compile(r"-m\s+([\w.]+)")
_FILE = re.compile(r'"\{root\}\\([^"]+\.py)"')


def _venv_checkout(checkout: Path, launcher: Launcher) -> Path:
    return checkout.parents[2] if launcher.venv == "primary" else checkout


def _arguments(checkout: Path, launcher: Launcher) -> str:
    places = {"root": checkout, "checkout": checkout, "primary": _venv_checkout(checkout, launcher)}
    return re.sub(r"\{(\w+)\}", lambda found: str(places[found[1]]), launcher.run)


def _gates(checkout: Path, launcher: Launcher) -> list[str]:
    if not launcher.waits_for_updates:
        return []
    venv = _venv_checkout(checkout, launcher)
    turn = Path(".git") / production_update.TURN
    return [str(venv / turn), *(str(venv.parent / name / turn) for name in launcher.also_runs)]


def _pictures(checkout: Path, launcher: Launcher) -> list[str]:
    if not (launcher.preview and launcher.loading_screen):
        return []
    screen = PureWindowsPath(launcher.log).with_suffix(".screen")
    return [str(_venv_checkout(checkout, launcher) / screen / "preview")]


def _what_its_spec_says(checkout: Path, launcher: Launcher) -> dict[str, list[str]]:
    venv = _venv_checkout(checkout, launcher)
    return {
        "directory": [str(checkout)],
        "arguments": [_arguments(checkout, launcher)],
        "log": [str(checkout / launcher.log)] if launcher.log else [],
        "environment": [f"{name}={value}" for name, value in launcher.environment],
        "copy": [f"{venv / name} > {checkout / name}" for name in launcher.copy_from_primary],
        "gate": _gates(checkout, launcher),
        "pictures": _pictures(checkout, launcher),
    }


def _report_differences(checkout: Path, launcher: Launcher) -> list[str]:
    arguments = (str(checkout),) if launcher.checkout_argument else ()
    report = dry_run(checkout / launcher.file, *arguments)
    scripts = _venv_checkout(checkout, launcher) / ".venv" / "Scripts"
    interpreters = {str(scripts / name) for name in (launcher.interpreter, launcher.named_interpreter) if name}
    problems = [f"{launcher.file}: {key} is {report.values(key)}, its spec says {held}"
                for key, held in _what_its_spec_says(checkout, launcher).items() if report.values(key) != held]
    if report.value("interpreter") not in interpreters:
        problems.append(f"{launcher.file}: interpreter is {report.value('interpreter')}, "
                        f"its spec says one of {sorted(interpreters)}")
    return problems


def assert_every_launcher_reports_its_spec(checkout: Path) -> None:
    __tracebackhide__ = True
    problems = [problem for launcher in launchers(checkout) for problem in _report_differences(checkout, launcher)]
    assert not problems, "under the real script host:\n  " + "\n  ".join(problems)


def _is_there(checkout: Path, run: str) -> bool:
    if module := _MODULE.search(run):
        path = checkout.joinpath(*module[1].split("."))
        return path.with_suffix(".py").is_file() or (path / "__main__.py").is_file()
    return bool((file := _FILE.search(run)) and (checkout / file[1]).is_file())


def assert_what_every_launcher_runs_is_there(checkout: Path) -> None:
    __tracebackhide__ = True
    missing = [f"{launcher.file}: {launcher.run}" for launcher in launchers(checkout)
               if not _is_there(checkout, launcher.run)]
    assert not missing, "these launchers run something this checkout does not hold:\n  " + "\n  ".join(missing)


def assert_every_launcher_keeps_a_log(checkout: Path, *, without: Iterable[str]) -> None:
    __tracebackhide__ = True
    with_no_log = {launcher.file for launcher in launchers(checkout) if not launcher.log}
    assert with_no_log == set(without), (
        f"these launchers keep no log, and [tool.haglio.launcher-gate] without-a-log lists {sorted(without)}: "
        f"{sorted(with_no_log)}")


def assert_what_a_shortcut_or_a_task_starts_runs_on_its_own_venv(checkout: Path) -> None:
    __tracebackhide__ = True
    declared = windows_settings.declared(checkout)
    started = {spec.launcher for spec in (*declared.shortcuts, *declared.scheduled_tasks)}
    wrong = [launcher.file for launcher in launchers(checkout) if launcher.file in started and launcher.venv != "own"]
    assert not wrong, f"a shortcut or a scheduled task starts these, so each runs on its own checkout's venv: {wrong}"


def assert_a_branch_can_be_tried(checkout: Path, *, is_a_library: bool = False) -> None:
    __tracebackhide__ = True
    found = launchers(checkout)
    assert is_a_library or not found or any(launcher.preview for launcher in found), (
        "this repo's launchers include no preview, so a branch of it can be looked at only as a diff")

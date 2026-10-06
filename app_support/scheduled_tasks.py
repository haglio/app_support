"""Windows' Task Scheduler, driven through its own command-line tool.

The tool writes to a pipe in the console's OEM code page, whatever the XML it
prints says about UTF-16, and it reads a task's XML only from a file.

Standard library only.
"""
from __future__ import annotations

import csv
import os
import subprocess
import tempfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

from app_support.subprocess_utils import hidden_subprocess_kwargs

_NAMESPACE = "http://schemas.microsoft.com/windows/2004/02/mit/task"
_REPEATS_COUNTED_FROM = "2026-01-01T00:00:00"
_SETTINGS = (
    ("MultipleInstancesPolicy", "IgnoreNew"),
    ("StartWhenAvailable", "true"),
    ("DisallowStartIfOnBatteries", "false"),
    ("StopIfGoingOnBatteries", "false"),
    ("ExecutionTimeLimit", "PT0S"),
    ("Priority", "5"),
)


@dataclass(frozen=True)
class RecurringTask:
    path: str
    description: str
    command: str
    arguments: str
    working_directory: str
    every_minutes: int


def render(task: RecurringTask, *, user: str) -> str:
    root = ET.Element("Task", version="1.3", xmlns=_NAMESPACE)
    _child(_child(root, "RegistrationInfo"), "Description", text=task.description)
    principal = _child(_child(root, "Principals"), "Principal", id="Author")
    _child(principal, "LogonType", text="InteractiveToken")
    settings = _child(root, "Settings")
    for name, value in _SETTINGS:
        _child(settings, name, text=value)
    triggers = _child(root, "Triggers")
    _child(_child(triggers, "LogonTrigger"), "UserId", text=user)
    repeating = _child(triggers, "TimeTrigger")
    _child(repeating, "StartBoundary", text=_REPEATS_COUNTED_FROM)
    _child(_child(repeating, "Repetition"), "Interval", text=f"PT{task.every_minutes}M")
    action = _child(_child(root, "Actions", Context="Author"), "Exec")
    _child(action, "Command", text=task.command)
    _child(action, "Arguments", text=task.arguments)
    _child(action, "WorkingDirectory", text=task.working_directory)
    return ET.tostring(root, encoding="unicode")


def _child(parent: ET.Element, tag: str, *, text: str | None = None, **attributes: str) -> ET.Element:
    element = ET.SubElement(parent, tag, attributes)
    element.text = text
    return element


def what_differs(wanted: str, registered: str) -> list[str]:
    """Each value *wanted* states that *registered* does not hold.  What Task
    Scheduler adds of its own is not a difference."""
    holds = _values(registered)
    differences = []
    for path, value in _values(wanted).items():
        found = holds.get(path)
        if found is None:
            differences.append(f"{path}: nothing instead of {value}")
        elif found.casefold() != value.casefold():
            differences.append(f"{path}: {found} instead of {value}")
    return differences


def description_of(xml: str) -> str:
    return _values(xml).get("RegistrationInfo/Description", "")


def _values(xml: str) -> dict[str, str]:
    values: dict[str, str] = {}

    def walk(element: ET.Element, path: str) -> None:
        children = list(element)
        if not children:
            values[path] = (element.text or "").strip()
        for child in children:
            name = child.tag.rpartition("}")[2]
            walk(child, f"{path}/{name}" if path else name)

    walk(ET.fromstring(xml), "")
    return values


def this_user() -> str:
    return f"{os.environ['USERDOMAIN']}\\{os.environ['USERNAME']}"


def schtasks(*arguments: str) -> str:
    tool = Path(os.environ.get("SYSTEMROOT", r"C:\Windows")) / "System32" / "schtasks.exe"
    finished = subprocess.run([str(tool), *arguments], capture_output=True, check=False,
                              **hidden_subprocess_kwargs())
    output = finished.stdout.decode("oem", errors="replace")
    if finished.returncode != 0:
        complaint = finished.stderr.decode("oem", errors="replace").strip() or output.strip()
        raise OSError(f"schtasks {' '.join(arguments)}: {complaint}")
    return output


def tasks_in(folder: str, *, run=schtasks) -> list[str]:
    prefix = folder.rstrip("\\").casefold() + "\\"
    found: list[str] = []
    for row in csv.reader(run("/query", "/fo", "csv", "/nh").splitlines()):
        path = row[0] if row else ""
        inside = path.casefold().startswith(prefix) and "\\" not in path[len(prefix):]
        if inside and path not in found:
            found.append(path)
    return found


def registered(path: str, *, run=schtasks) -> str:
    return run("/query", "/tn", path, "/xml")


def register(path: str, xml: str, *, run=schtasks) -> None:
    with tempfile.TemporaryDirectory() as folder:
        task_file = Path(folder) / "task.xml"
        task_file.write_text('<?xml version="1.0" encoding="UTF-16"?>\n' + xml, encoding="utf-16")
        run("/create", "/tn", path, "/xml", str(task_file), "/f")


def delete(path: str, *, run=schtasks) -> None:
    run("/delete", "/tn", path, "/f")

from __future__ import annotations

import contextlib
import dataclasses
import subprocess
import sys
import uuid
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from app_support import scheduled_tasks
from app_support.scheduled_tasks import RecurringTask

NAMESPACE = "{http://schemas.microsoft.com/windows/2004/02/mit/task}"

EXAMPLE = RecurringTask(
    path="\\Example\\Example Tray",
    description="Starts Example's tray.",
    command="C:\\Windows\\System32\\wscript.exe",
    arguments='"C:\\example\\launch_example.vbs"',
    working_directory="C:\\example",
    every_minutes=2,
)


def _leaf(xml: str, path: str) -> str:
    element = ET.fromstring(xml).find("/".join(NAMESPACE + step for step in path.split("/")))
    assert element is not None, f"{path} is not in\n{xml}"
    return element.text or ""


class TestTheRendering:
    def test_the_task_starts_its_command_in_its_folder(self):
        xml = scheduled_tasks.render(EXAMPLE, user="EXAMPLE\\someone")

        assert _leaf(xml, "Actions/Exec/Command") == "C:\\Windows\\System32\\wscript.exe"
        assert _leaf(xml, "Actions/Exec/Arguments") == '"C:\\example\\launch_example.vbs"'
        assert _leaf(xml, "Actions/Exec/WorkingDirectory") == "C:\\example"

    def test_it_starts_when_the_user_signs_in_and_every_so_many_minutes_after(self):
        xml = scheduled_tasks.render(EXAMPLE, user="EXAMPLE\\someone")

        assert _leaf(xml, "Triggers/LogonTrigger/UserId") == "EXAMPLE\\someone"
        assert _leaf(xml, "Triggers/TimeTrigger/Repetition/Interval") == "PT2M"

    def test_the_repeats_need_no_date_of_registration(self):
        """A repeat counted from the day it was registered would make two
        registrations of one task differ, and every check say it had changed."""
        assert (scheduled_tasks.render(EXAMPLE, user="EXAMPLE\\someone")
                == scheduled_tasks.render(EXAMPLE, user="EXAMPLE\\someone"))
        assert _leaf(scheduled_tasks.render(EXAMPLE, user="EXAMPLE\\someone"),
                     "Triggers/TimeTrigger/StartBoundary") == "2026-01-01T00:00:00"

    def test_it_runs_as_the_user_at_the_desk_without_asking_for_a_password(self):
        xml = scheduled_tasks.render(EXAMPLE, user="EXAMPLE\\someone")

        assert _leaf(xml, "Principals/Principal/LogonType") == "InteractiveToken"

    def test_a_start_that_is_still_running_is_never_doubled(self):
        xml = scheduled_tasks.render(EXAMPLE, user="EXAMPLE\\someone")

        assert _leaf(xml, "Settings/MultipleInstancesPolicy") == "IgnoreNew"

    def test_a_start_missed_while_the_machine_slept_is_made_up(self):
        xml = scheduled_tasks.render(EXAMPLE, user="EXAMPLE\\someone")

        assert _leaf(xml, "Settings/StartWhenAvailable") == "true"

    def test_it_starts_and_keeps_running_on_battery(self):
        xml = scheduled_tasks.render(EXAMPLE, user="EXAMPLE\\someone")

        assert _leaf(xml, "Settings/DisallowStartIfOnBatteries") == "false"
        assert _leaf(xml, "Settings/StopIfGoingOnBatteries") == "false"

    def test_what_it_starts_is_never_stopped_for_running_long(self):
        xml = scheduled_tasks.render(EXAMPLE, user="EXAMPLE\\someone")

        assert _leaf(xml, "Settings/ExecutionTimeLimit") == "PT0S"

    def test_what_it_starts_runs_at_the_priority_a_click_would_give_it(self):
        """Task Scheduler's own default is below normal, which a program started
        from a task passes on to everything it starts in turn."""
        xml = scheduled_tasks.render(EXAMPLE, user="EXAMPLE\\someone")

        assert _leaf(xml, "Settings/Priority") == "5"

    def test_the_task_says_what_it_is(self):
        xml = scheduled_tasks.render(EXAMPLE, user="EXAMPLE\\someone")

        assert _leaf(xml, "RegistrationInfo/Description") == "Starts Example's tray."


def _as_registered(xml: str, **changes: str | None) -> str:
    """*xml* the way Task Scheduler hands a task back: with values of its own
    added, and with *changes* -- a path to a new value, or None to drop it."""
    root = ET.fromstring(xml)
    ET.SubElement(root.find(NAMESPACE + "RegistrationInfo"), NAMESPACE + "URI").text = "\\x"
    idle = ET.SubElement(root.find(NAMESPACE + "Settings"), NAMESPACE + "IdleSettings")
    ET.SubElement(idle, NAMESPACE + "StopOnIdleEnd").text = "true"
    for path, value in changes.items():
        steps = [NAMESPACE + step for step in path.split("__")]
        parent = root.find("/".join(steps[:-1])) if len(steps) > 1 else root
        element = parent.find(steps[-1])
        if value is None:
            parent.remove(element)
        else:
            element.text = value
    return ET.tostring(root, encoding="unicode")


class TestWhatDiffers:
    WANTED = scheduled_tasks.render(EXAMPLE, user="EXAMPLE\\someone")

    def test_a_task_holding_every_value_wanted_differs_in_nothing(self):
        assert scheduled_tasks.what_differs(self.WANTED, _as_registered(self.WANTED)) == []

    def test_a_value_that_changed_is_named_with_both_spellings(self):
        registered = _as_registered(
            self.WANTED, Actions__Exec__Arguments='"C:\\old\\launch_example.vbs"')

        (difference,) = scheduled_tasks.what_differs(self.WANTED, registered)
        assert difference == ('Actions/Exec/Arguments: "C:\\old\\launch_example.vbs"'
                              ' instead of "C:\\example\\launch_example.vbs"')

    def test_a_value_the_registered_task_lacks_is_named(self):
        registered = _as_registered(self.WANTED, Settings__Priority=None)

        assert scheduled_tasks.what_differs(self.WANTED, registered) == [
            "Settings/Priority: nothing instead of 5"]

    def test_case_alone_is_no_difference(self):
        registered = _as_registered(
            self.WANTED, Actions__Exec__Command="c:\\windows\\system32\\WSCRIPT.EXE")

        assert scheduled_tasks.what_differs(self.WANTED, registered) == []


class TestWhatATaskSaysItIs:
    def test_a_registered_task_says_what_it_was_registered_as(self):
        registered = _as_registered(scheduled_tasks.render(EXAMPLE, user="EXAMPLE\\someone"))

        assert scheduled_tasks.description_of(registered) == "Starts Example's tray."

    def test_a_task_registered_with_no_description_says_nothing(self):
        registered = _as_registered(scheduled_tasks.render(EXAMPLE, user="EXAMPLE\\someone"),
                                    RegistrationInfo__Description=None)

        assert scheduled_tasks.description_of(registered) == ""


class _Schtasks:
    """Task Scheduler's command-line tool as far as these calls use it: what it
    was asked, and what it answers."""

    def __init__(self, answer: str = "", *, refusal: str | None = None) -> None:
        self.answer = answer
        self.refusal = refusal
        self.calls: list[tuple[str, ...]] = []
        self.files: list[bytes] = []

    def __call__(self, *arguments: str) -> str:
        self.calls.append(arguments)
        if "/xml" in arguments and arguments.index("/xml") + 1 < len(arguments):
            self.files.append(Path(arguments[arguments.index("/xml") + 1]).read_bytes())
        if self.refusal is not None:
            raise OSError(self.refusal)
        return self.answer


LISTING = r'''
"\Example\Example Tray","06/10/2026 13:56:49","Ready"
"\Example\Example Tray","06/10/2026 13:56:49","Ready"
"\Example\Other","N/A","Ready"
"\Example\Deeper\Task","N/A","Ready"
"\example tray","N/A","Ready"
"\Elsewhere\Example Tray","N/A","Disabled"
'''


class TestTheCommandLineTool:
    def test_the_tasks_directly_in_a_folder_are_listed_once_each(self):
        schtasks = _Schtasks(LISTING)

        assert scheduled_tasks.tasks_in("\\Example", run=schtasks) == [
            "\\Example\\Example Tray", "\\Example\\Other"]

    def test_only_the_folder_is_asked_for(self):
        """Every folder on the machine took a busy runner more than a minute to
        list; one folder takes what that folder holds."""
        schtasks = _Schtasks(LISTING)

        scheduled_tasks.tasks_in("\\Example", run=schtasks)

        assert schtasks.calls == [("/query", "/tn", "\\Example\\", "/fo", "csv", "/nh")]

    def test_a_folder_is_matched_whatever_its_case(self):
        assert scheduled_tasks.tasks_in("\\EXAMPLE\\", run=_Schtasks(LISTING)) == [
            "\\Example\\Example Tray", "\\Example\\Other"]

    def test_a_folder_task_scheduler_does_not_have_holds_nothing(self):
        missing = _Schtasks(refusal="ERROR: The system cannot find the file specified.")

        assert scheduled_tasks.tasks_in("\\Example", run=missing) == []

    def test_a_registered_task_is_read_back_as_it_is_registered(self):
        schtasks = _Schtasks("<Task/>")

        assert scheduled_tasks.registered("\\Example\\Example Tray", run=schtasks) == "<Task/>"
        assert schtasks.calls == [("/query", "/tn", "\\Example\\Example Tray", "/xml")]

    def test_a_task_is_registered_over_whatever_had_its_path(self):
        schtasks = _Schtasks()
        xml = scheduled_tasks.render(EXAMPLE, user="EXAMPLE\\someone")

        scheduled_tasks.register(EXAMPLE.path, xml, run=schtasks)

        ((create, name, path, xml_flag, _file, force),) = schtasks.calls
        assert (create, name, path, xml_flag, force) == (
            "/create", "/tn", "\\Example\\Example Tray", "/xml", "/f")

    def test_the_file_registered_is_the_task_in_the_encoding_it_declares(self):
        schtasks = _Schtasks()
        xml = scheduled_tasks.render(EXAMPLE, user="EXAMPLE\\someone")

        scheduled_tasks.register(EXAMPLE.path, xml, run=schtasks)

        (registered_file,) = schtasks.files
        text = registered_file.decode("utf-16")
        assert text.startswith('<?xml version="1.0" encoding="UTF-16"?>')
        assert scheduled_tasks.what_differs(xml, text) == []

    def test_the_file_is_gone_once_the_task_is_registered(self, tmp_path):
        schtasks = _Schtasks()

        scheduled_tasks.register(
            EXAMPLE.path, scheduled_tasks.render(EXAMPLE, user="EXAMPLE\\someone"), run=schtasks)

        ((*_, registered_file, _force),) = schtasks.calls
        assert not Path(registered_file).exists()

    def test_a_task_is_deleted_without_a_question(self):
        schtasks = _Schtasks()

        scheduled_tasks.delete("\\Example\\Example Tray", run=schtasks)

        assert schtasks.calls == [("/delete", "/tn", "\\Example\\Example Tray", "/f")]

    def test_a_refusal_reaches_the_caller(self):
        schtasks = _Schtasks(refusal="ERROR: Access is denied.")

        with pytest.raises(OSError, match="Access is denied"):
            scheduled_tasks.delete("\\Example\\Example Tray", run=schtasks)

    def test_a_tool_that_never_answers_is_a_refusal_rather_than_a_hang(self, monkeypatch):
        def never_answers(*arguments, **options):
            raise subprocess.TimeoutExpired(arguments[0], options["timeout"])

        monkeypatch.setattr(scheduled_tasks.subprocess, "run", never_answers)

        with pytest.raises(OSError, match="no answer"):
            scheduled_tasks.schtasks("/query", "/tn", "\\Example\\", "/fo", "csv", "/nh")

    def test_the_tool_is_never_left_waiting_for_input(self, monkeypatch):
        asked: dict = {}

        def answered(arguments, **options):
            asked.update(options)
            return subprocess.CompletedProcess(arguments, 0, b"", b"")

        monkeypatch.setattr(scheduled_tasks.subprocess, "run", answered)

        scheduled_tasks.schtasks("/query", "/tn", "\\Example\\", "/fo", "csv", "/nh")

        assert asked["stdin"] is subprocess.DEVNULL

    def test_the_user_is_the_one_signed_in(self, monkeypatch):
        monkeypatch.setenv("USERDOMAIN", "EXAMPLE")
        monkeypatch.setenv("USERNAME", "someone")

        assert scheduled_tasks.this_user() == "EXAMPLE\\someone"


def _never_started(xml: str) -> str:
    """*xml* with the task switched off, so registering it here starts nothing."""
    root = ET.fromstring(xml)
    ET.SubElement(root.find(NAMESPACE + "Settings"), NAMESPACE + "Enabled").text = "false"
    return ET.tostring(root, encoding="unicode")


@pytest.mark.skipif(sys.platform != "win32", reason="Task Scheduler: only Windows can say")
class TestARealRegistration:
    """What only Task Scheduler can say: that it takes the rendered task, without
    an administrator, and hands back every value it was given."""

    FOLDER = "\\Haglio"

    @pytest.fixture
    def path(self):
        path = f"{self.FOLDER}\\Example test {uuid.uuid4().hex[:12]}"
        yield path
        with contextlib.suppress(OSError):
            scheduled_tasks.delete(path)

    def test_every_value_rendered_is_registered(self, path, tmp_path):
        task = dataclasses.replace(EXAMPLE, path=path, working_directory=str(tmp_path),
                                   arguments=f'"{tmp_path / "launch_example.vbs"}"')
        xml = _never_started(scheduled_tasks.render(task, user=scheduled_tasks.this_user()))

        scheduled_tasks.register(path, xml)

        assert path in scheduled_tasks.tasks_in(self.FOLDER)
        assert scheduled_tasks.what_differs(xml, scheduled_tasks.registered(path)) == []

    def test_a_deleted_task_is_gone(self, path):
        scheduled_tasks.register(path, _never_started(
            scheduled_tasks.render(EXAMPLE, user=scheduled_tasks.this_user())))

        scheduled_tasks.delete(path)

        assert path not in scheduled_tasks.tasks_in(self.FOLDER)

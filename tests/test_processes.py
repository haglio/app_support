"""What is running on this machine and whose it is, read through Win32 alone."""
from __future__ import annotations

import os
import subprocess
import sys
import time
import uuid

import pytest
from git_bash_programs import waited_for

from app_support import processes

windows_only = pytest.mark.skipif(sys.platform != "win32", reason="Win32's processes")

# The interpreter itself rather than a venv's python.exe, which is a stub that runs
# the interpreter as a second process carrying the same command line.
PYTHON = sys._base_executable
HIS_DESKTOP = "WinSta0\\Default"
CLAUDE_CODE = r"C:\Users\Someone\AppData\Roaming\Claude\claude-code\2.1.275\claude.exe"
DESKTOP_APP = r"C:\Program Files\WindowsApps\Claude_2.2553.1.0_x64\app\Claude.exe"


def _marker() -> str:
    return "processes-test-" + uuid.uuid4().hex


@pytest.fixture
def sleeper():
    started = []

    def start(*arguments: str, env: dict[str, str] | None = None, creationflags: int = 0) -> subprocess.Popen:
        child = subprocess.Popen([PYTHON, "-c", "print(flush=True); import time; time.sleep(120)", *arguments],
                                 env=env, creationflags=creationflags, stdout=subprocess.PIPE)
        started.append(child)
        child.stdout.readline()
        return child

    yield start
    for child in started:
        child.kill()
        child.wait()


def _the(child: subprocess.Popen) -> processes.Process:
    return waited_for(lambda process: process.pid == child.pid and process.cmdline, str(child.pid))


@windows_only
class TestWhatIsRunning:
    def test_a_process_is_found_with_its_command_line(self, sleeper):
        marker = _marker()
        child = sleeper(marker)

        assert [process.pid for process in processes.running() if marker in process.cmdline] == [child.pid]

    def test_the_command_line_reads_as_one_line_of_its_arguments(self, sleeper):
        marker = _marker()

        found = _the(sleeper(f"two  words\n{marker}", '"quoted"'))

        assert f'two words {marker} "quoted"' in found.cmdline

    def test_it_says_what_started_it_when_and_from_where(self, sleeper):
        before = time.time()

        found = _the(sleeper(_marker()))

        assert found.ppid == os.getpid()
        assert before - 5 <= found.started <= time.time() + 5
        assert found.name.lower() == os.path.basename(PYTHON).lower()
        assert os.path.normcase(found.exe) == os.path.normcase(PYTHON)

    def test_a_process_that_has_ended_is_not_running_while_its_handle_is_still_held(self, sleeper):
        child = sleeper(_marker())
        _the(child)
        child.kill()
        child.wait()

        assert child.pid not in {process.pid for process in processes.running()}

    def test_this_process_and_each_of_its_parents_are_its_own_chain(self):
        among = {process.pid: process for process in processes.running()}

        chain = processes.this_process_and_its_parents(among)

        assert {os.getpid(), os.getppid()} <= chain

    def test_a_childs_parents_start_with_the_process_that_started_it(self, sleeper):
        child = _the(sleeper(_marker()))
        among = {process.pid: process for process in processes.running()}

        assert processes.ancestors(child, among)[0].pid == os.getpid()

    def test_a_parent_younger_than_its_child_is_a_stranger_wearing_its_pid(self):
        child = processes.Process(pid=20, ppid=10, started=100.0, name="child.exe", exe="", cmdline="")
        stranger = processes.Process(pid=10, ppid=1, started=200.0, name="other.exe", exe="", cmdline="")

        assert processes.ancestors(child, {10: stranger, 20: child}) == []


@windows_only
class TestTheMarksOnAProcess:
    def test_reads_the_mark_a_claude_code_session_leaves_on_what_it_starts(self, sleeper):
        marked = sleeper(_marker(), env={**os.environ, processes.SESSION_MARK: "1"})
        bare = sleeper(_marker(), env={k: v for k, v in os.environ.items() if k != processes.SESSION_MARK})
        _the(marked)
        _the(bare)

        assert processes.SESSION_MARK in processes.environment_names(marked.pid)
        assert processes.SESSION_MARK not in processes.environment_names(bare.pid)

    def test_a_process_that_has_gone_has_no_environment_to_read(self, sleeper):
        child = sleeper(_marker())
        child.kill()
        child.wait()

        assert processes.environment_names(child.pid) == frozenset()

    def test_reads_the_files_a_process_writes_its_output_and_errors_to(self, tmp_path):
        with (tmp_path / "out.txt").open("w") as out, (tmp_path / "errors.txt").open("w") as errors:
            child = subprocess.Popen([PYTHON, "-c", "import time; time.sleep(120)"], stdout=out, stderr=errors)
        try:
            _the(child)

            assert {os.path.normcase(path) for path in processes.output_files(child.pid)} == {
                os.path.normcase(str((tmp_path / name).resolve())) for name in ("out.txt", "errors.txt")}
        finally:
            child.kill()
            child.wait()

    def test_a_process_writing_to_a_pipe_writes_to_no_file(self):
        child = subprocess.Popen([PYTHON, "-c", "import time; time.sleep(120)"],
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            _the(child)

            assert processes.output_files(child.pid) == frozenset()
        finally:
            child.kill()
            child.communicate()

    def test_reads_the_desktop_this_very_process_runs_on(self):
        assert processes.desktop_of(os.getpid())

    def test_reads_the_desktop_of_a_process_started_on_another_one(self, child_on_its_own_desktop):
        desktop, pid = child_on_its_own_desktop

        assert processes.desktop_of(pid) == desktop


@windows_only
class TestTheConsoleAProcessRunsIn:
    def test_a_child_given_a_console_of_its_own_is_served_by_a_console_host_of_its_own(self, sleeper):
        child = sleeper(_marker(), creationflags=subprocess.CREATE_NO_WINDOW)

        host = processes.console_host_of(child.pid)

        assert host != processes.console_host_of(os.getpid())
        assert {process.pid: process for process in processes.running()}[host].name.lower() == "conhost.exe"


class TestWhoseItIs:
    def test_a_process_on_any_desktop_but_his_is_offscreen_whoever_started_it(self):
        assert processes.whose("FunTimeIntegration") == processes.OFFSCREEN
        assert processes.whose("Empty4412", environment=[processes.SESSION_MARK]) == processes.OFFSCREEN

    def test_a_process_on_his_desktop_under_a_claude_code_session_is_an_agents(self):
        ancestors = [r"C:\Program Files\Git\bin\bash.exe", CLAUDE_CODE]

        assert processes.whose(HIS_DESKTOP, ancestor_exes=ancestors) == processes.AGENT

    def test_a_process_that_lost_its_parents_still_carries_the_session_it_came_from(self):
        assert processes.whose(HIS_DESKTOP, environment=["PATH", processes.SESSION_MARK]) == processes.AGENT

    def test_a_process_that_only_hands_the_session_on_to_what_it_starts_is_an_agents(self):
        # Git's env.exe, a stub of its POSIX runtime, keeps a Windows environment of a few names
        # and loses its parent when the shell that ran it ends; what it starts carries the mark.
        # Judged his, an agent's `env -C <dir> python -m pytest` held back his updates (2026-10-17).
        assert processes.whose(HIS_DESKTOP, environment=["PATH"],
                               child_environments=[["PATH"], ["PATH", processes.SESSION_MARK]]) == processes.AGENT

    def test_the_claude_desktop_app_is_not_an_agent_so_what_he_opens_from_it_stays_his(self):
        ancestors = [DESKTOP_APP, r"C:\windows\explorer.exe"]

        assert processes.whose("Winsta0\\Default", ancestor_exes=ancestors) == processes.HIS

    def test_a_setting_of_his_that_every_process_inherits_is_not_the_mark_of_a_session(self):
        assert processes.whose(HIS_DESKTOP, environment=["CLAUDE_CODE_EFFORT_LEVEL"]) == processes.HIS

    def test_a_process_whose_desktop_cannot_be_read_is_treated_as_his(self):
        assert processes.whose(None) == processes.HIS
        assert processes.whose("") == processes.HIS

    def test_whose_a_process_is_also_read_from_the_processes_it_started(self, monkeypatch):
        stub = processes.Process(pid=10, ppid=1, started=100.0, name="env.exe", exe="env.exe", cmdline="env")
        started = processes.Process(pid=11, ppid=10, started=101.0, name="python.exe", exe=PYTHON, cmdline="")
        marks = {10: frozenset({"PATH"}), 11: frozenset({"PATH", processes.SESSION_MARK})}
        monkeypatch.setattr(processes, "desktop_of", lambda pid: HIS_DESKTOP)
        monkeypatch.setattr(processes, "environment_names", lambda pid: marks[pid])

        assert processes.whose_process(stub, {10: stub, 11: started}) == processes.AGENT

    def test_a_process_older_than_the_one_it_names_as_its_parent_was_never_started_by_it(self, monkeypatch):
        stub = processes.Process(pid=10, ppid=1, started=100.0, name="env.exe", exe="env.exe", cmdline="env")
        stranger = processes.Process(pid=12, ppid=10, started=50.0, name="python.exe", exe=PYTHON, cmdline="")
        marks = {10: frozenset({"PATH"}), 12: frozenset({"PATH", processes.SESSION_MARK})}
        monkeypatch.setattr(processes, "desktop_of", lambda pid: HIS_DESKTOP)
        monkeypatch.setattr(processes, "environment_names", lambda pid: marks[pid])

        assert processes.whose_process(stub, {10: stub, 12: stranger}) == processes.HIS

    @windows_only
    def test_whose_a_running_process_is_comes_from_its_desktop(self, child_on_its_own_desktop):
        _, pid = child_on_its_own_desktop
        among = {process.pid: process for process in processes.running()}

        assert processes.whose_process(among[pid], among) == processes.OFFSCREEN


@windows_only
class TestWhatGitBashStarts:
    def test_a_program_it_starts_from_one_of_its_own_carries_the_session_it_came_from(self, started_by_git_bash):
        _, program = started_by_git_bash({**os.environ, processes.SESSION_MARK: "1"})

        assert processes.SESSION_MARK in processes.environment_names(program.pid)

    def test_one_started_outside_any_session_carries_no_mark_of_one(self, started_by_git_bash):
        _, program = started_by_git_bash({k: v for k, v in os.environ.items() if k != processes.SESSION_MARK})

        assert "PATH" in processes.environment_names(program.pid)
        assert processes.SESSION_MARK not in processes.environment_names(program.pid)

    def test_a_program_it_starts_from_one_of_its_own_stays_the_agents_once_that_shell_has_gone(
            self, started_by_git_bash, monkeypatch):
        shell, program = started_by_git_bash({**os.environ, processes.SESSION_MARK: "1"})
        shell.kill()
        shell.wait()
        monkeypatch.setattr(processes, "desktop_of", lambda pid: HIS_DESKTOP)
        among = {process.pid: process for process in processes.running()}

        assert processes.whose_process(among[program.pid], among) == processes.AGENT

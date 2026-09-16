from __future__ import annotations

import os
import subprocess
import sys
from contextlib import contextmanager, nullcontext
from pathlib import Path

import pytest

from app_support import flake_gate
from app_support.flake_gate import assert_they_hold_up, busy_machine

windows_only = pytest.mark.skipif(sys.platform != "win32", reason="priority classes are Windows'")

FAILS_ON_ITS_SECOND_RUN = '''
from pathlib import Path

COUNT = Path(__file__).with_name("runs.txt")


def test_sometimes():
    runs = int(COUNT.read_text()) + 1 if COUNT.exists() else 1
    COUNT.write_text(str(runs))
    assert runs != 2
'''


def test_a_test_that_always_passes_holds_up(tmp_path: Path):
    (tmp_path / "test_steady.py").write_text("def test_steady():\n    assert True\n", encoding="utf-8")

    assert_they_hold_up(tmp_path, ["test_steady.py::test_steady"], runs=3, load=nullcontext)


def test_nothing_to_repeat_runs_nothing_at_all(tmp_path: Path):
    """An empty list handed to pytest is the whole suite, ten times over."""
    (tmp_path / "test_broken.py").write_text("def test_broken():\n    assert False\n", encoding="utf-8")
    loads = []

    @contextmanager
    def load():
        loads.append("busy")
        yield

    assert_they_hold_up(tmp_path, [], runs=3, load=load)

    assert loads == []


def test_a_test_that_fails_on_one_run_of_several_is_refused(tmp_path: Path):
    (tmp_path / "test_flaky.py").write_text(FAILS_ON_ITS_SECOND_RUN, encoding="utf-8")

    with pytest.raises(AssertionError):
        assert_they_hold_up(tmp_path, ["test_flaky.py::test_sometimes"], runs=3, load=nullcontext)


def test_every_run_happens_while_the_machine_is_kept_busy(tmp_path: Path):
    log = tmp_path / "log.txt"
    (tmp_path / "test_logged.py").write_text(
        "from pathlib import Path\n\n\n"
        "def test_logged():\n"
        "    with Path(__file__).with_name('log.txt').open('a') as log:\n"
        "        log.write('run\\n')\n", encoding="utf-8")

    @contextmanager
    def load():
        with log.open("a") as f:
            f.write("busy\n")
        yield
        with log.open("a") as f:
            f.write("idle\n")

    assert_they_hold_up(tmp_path, ["test_logged.py::test_logged"], runs=2, load=load)

    assert log.read_text().split() == ["busy", "run", "run", "idle"]


def test_the_refusal_says_which_run_failed_and_carries_what_it_printed(tmp_path: Path):
    (tmp_path / "test_flaky.py").write_text(FAILS_ON_ITS_SECOND_RUN, encoding="utf-8")

    with pytest.raises(AssertionError) as refused:
        assert_they_hold_up(tmp_path, ["test_flaky.py::test_sometimes"], runs=3, load=nullcontext)

    assert "run 2 of 3" in str(refused.value)
    assert "assert 2 != 2" in str(refused.value)


def test_a_busy_machine_keeps_its_workers_spinning_until_it_is_left():
    with busy_machine(workers=2) as workers:
        assert len(workers) == 2
        assert all(worker.poll() is None for worker in workers)

    assert all(worker.poll() is not None for worker in workers)


def _priority_class(pid: int) -> int:
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32")
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.GetPriorityClass.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
    try:
        return kernel32.GetPriorityClass(handle)
    finally:
        kernel32.CloseHandle(handle)


OWN_PRIORITY = (
    "import ctypes\n"
    "from ctypes import wintypes\n"
    "from pathlib import Path\n\n\n"
    "def test_own_priority():\n"
    "    kernel32 = ctypes.WinDLL('kernel32')\n"
    "    kernel32.GetCurrentProcess.restype = wintypes.HANDLE\n"
    "    kernel32.GetPriorityClass.argtypes = [wintypes.HANDLE]\n"
    "    own = kernel32.GetPriorityClass(kernel32.GetCurrentProcess())\n"
    "    Path(__file__).with_name('priority.txt').write_text(str(own))\n"
)


@windows_only
def test_the_workers_give_way_to_whatever_he_is_using():
    with busy_machine(workers=1) as workers:
        assert _priority_class(workers[0].pid) == subprocess.BELOW_NORMAL_PRIORITY_CLASS


@windows_only
def test_on_a_machine_nobody_is_using_the_workers_compete_with_the_runs():
    with busy_machine(workers=1, give_way=False) as workers:
        assert _priority_class(workers[0].pid) == _priority_class(os.getpid())


@windows_only
def test_the_runs_keep_the_priority_the_gate_was_started_with(tmp_path: Path):
    """Lowered, a test waiting on a child of its own was starved by the other
    sessions' suites past its timeout, and the gate called it flaky.  A CI
    runner starts the whole job below normal, which the runs keep too."""
    (tmp_path / "test_own_priority.py").write_text(OWN_PRIORITY, encoding="utf-8")

    assert_they_hold_up(tmp_path, ["test_own_priority.py::test_own_priority"], runs=1, load=nullcontext)

    assert int((tmp_path / "priority.txt").read_text()) == _priority_class(os.getpid())


def test_unless_told_otherwise_it_keeps_every_core_busy(monkeypatch, tmp_path: Path):
    asked_for = []

    @contextmanager
    def counting(*, workers, give_way):
        asked_for.append(workers)
        yield []

    monkeypatch.setattr(flake_gate, "busy_machine", counting)
    (tmp_path / "test_steady.py").write_text("def test_steady():\n    assert True\n", encoding="utf-8")

    assert_they_hold_up(tmp_path, ["test_steady.py::test_steady"], runs=1)

    assert asked_for == [os.cpu_count()]


@contextmanager
def _idle(*, workers, give_way):
    yield []


OLD = "def test_old():\n    assert True\n"


def test_the_command_repeats_what_the_branch_added_and_lets_it_through(branch_from, monkeypatch, capsys):
    branch = branch_from({"tests/test_things.py": OLD})
    branch.commit({"tests/test_things.py": OLD + "\n\ndef test_new():\n    assert True\n"})
    monkeypatch.chdir(branch.path)
    monkeypatch.setattr(flake_gate, "busy_machine", _idle)

    assert flake_gate.main(["--base", "main", "--runs", "2"]) == 0
    assert "tests/test_things.py::test_new" in capsys.readouterr().out


def test_the_command_refuses_a_flaky_test_with_its_output(branch_from, monkeypatch, capsys):
    branch = branch_from({"tests/test_things.py": OLD})
    branch.commit({"tests/test_flaky.py": FAILS_ON_ITS_SECOND_RUN})
    monkeypatch.chdir(branch.path)
    monkeypatch.setattr(flake_gate, "busy_machine", _idle)

    assert flake_gate.main(["--base", "main", "--runs", "3"]) == 1
    assert "run 2 of 3" in capsys.readouterr().err


BROKEN = "def test_broken():\n    assert False\n"


KEEPS_OUT_INTEGRATION = '[tool.pytest.ini_options]\nnorecursedirs = ["integration"]\n'


def test_a_tree_the_suite_does_not_recurse_into_is_not_repeated(branch_from, monkeypatch, capsys):
    branch = branch_from({"pyproject.toml": KEEPS_OUT_INTEGRATION, "tests/test_things.py": OLD})
    branch.commit({"tests/integration/test_slow.py": BROKEN,
                   "tests/test_fast.py": "def test_fast():\n    assert True\n"})
    monkeypatch.chdir(branch.path)
    monkeypatch.setattr(flake_gate, "busy_machine", _idle)

    assert flake_gate.main(["--base", "main", "--runs", "1"]) == 0
    assert capsys.readouterr().out.split() == ["tests/test_fast.py::test_fast"]


def test_a_tree_the_command_is_limited_to_is_all_it_runs(branch_from, monkeypatch, capsys):
    branch = branch_from({"pyproject.toml": KEEPS_OUT_INTEGRATION, "tests/test_things.py": OLD})
    branch.commit({"tests/integration/test_slow.py": "def test_slow():\n    assert True\n",
                   "tests/test_fast.py": BROKEN})
    monkeypatch.chdir(branch.path)
    monkeypatch.setattr(flake_gate, "busy_machine", _idle)

    assert flake_gate.main(["--base", "main", "--runs", "1", "--only", "tests/integration/"]) == 0
    assert capsys.readouterr().out.split() == ["tests/integration/test_slow.py::test_slow"]


def test_the_runs_use_the_interpreter_they_are_given(tmp_path: Path, monkeypatch):
    started = []

    def run(argv, **kwargs):
        started.append(argv[0])
        return subprocess.CompletedProcess(argv, 0, "", "")

    monkeypatch.setattr(flake_gate.subprocess, "run", run)

    assert_they_hold_up(tmp_path, ["test_x.py::test_x"], runs=2, load=nullcontext,
                        python=r"C:\elsewhere\python.exe")

    assert started == [r"C:\elsewhere\python.exe"] * 2


def test_the_command_runs_the_tests_with_the_interpreter_it_is_named(branch_from, monkeypatch):
    branch = branch_from({"tests/test_things.py": OLD})
    branch.commit({"tests/test_new.py": "def test_new():\n    assert True\n"})
    monkeypatch.chdir(branch.path)
    asked = {}
    monkeypatch.setattr(flake_gate, "assert_they_hold_up",
                        lambda root, ids, **kwargs: asked.update(kwargs))

    assert flake_gate.main(["--base", "main", "--python", r"C:\suite\python.exe"]) == 0
    assert asked["python"] == r"C:\suite\python.exe"


def test_the_command_says_so_when_there_is_nothing_to_repeat(branch_from, monkeypatch, capsys):
    branch = branch_from({"tests/test_things.py": OLD, "app.py": "SIZE = 1\n"})
    branch.commit({"app.py": "SIZE = 2\n"})
    monkeypatch.chdir(branch.path)

    assert flake_gate.main(["--base", "main"]) == 0
    assert "no test was added or changed since main" in capsys.readouterr().err


def test_a_test_outside_the_suites_test_paths_is_not_repeated(branch_from, monkeypatch, capsys):
    branch = branch_from({"pyproject.toml": '[tool.pytest.ini_options]\ntestpaths = ["tests"]\n',
                          "tests/test_things.py": OLD})
    branch.commit({"package/test_shipped.py": BROKEN,
                   "tests/test_fast.py": "def test_fast():\n    assert True\n"})
    monkeypatch.chdir(branch.path)
    monkeypatch.setattr(flake_gate, "busy_machine", _idle)

    assert flake_gate.main(["--base", "main", "--runs", "1"]) == 0
    assert capsys.readouterr().out.split() == ["tests/test_fast.py::test_fast"]


def test_only_a_machine_named_dedicated_has_its_workers_compete(branch_from, monkeypatch):
    branch = branch_from({"tests/test_things.py": OLD})
    branch.commit({"tests/test_new.py": "def test_new():\n    assert True\n"})
    monkeypatch.chdir(branch.path)
    gave_way = []

    @contextmanager
    def recording(*, workers, give_way):
        gave_way.append(give_way)
        yield []

    monkeypatch.setattr(flake_gate, "busy_machine", recording)

    assert flake_gate.main(["--base", "main", "--runs", "1", "--dedicated-machine"]) == 0
    assert flake_gate.main(["--base", "main", "--runs", "1"]) == 0
    assert gave_way == [False, True]

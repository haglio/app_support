from __future__ import annotations

import time
from argparse import Namespace
from pathlib import Path

from consumer_runs import run_pytest_in

from app_support import worker_processes

_SAYS_IT_RUNS_BELOW_NORMAL = """\
import ctypes
import subprocess


def test_this_worker_runs_below_normal_priority():
    kernel32 = ctypes.WinDLL("kernel32")
    assert kernel32.GetPriorityClass(ctypes.c_void_p(-1)) == subprocess.BELOW_NORMAL_PRIORITY_CLASS
"""


def _repo(tmp_path: Path, test: str) -> Path:
    (tmp_path / "pyproject.toml").write_text(
        '[tool.pytest.ini_options]\naddopts = "-p no:cacheprovider -p app_support.repo_checks"\n', encoding="utf-8")
    (tmp_path / "test_it.py").write_text(test, encoding="utf-8")
    return tmp_path


def _controller(**options):
    return Namespace(option=Namespace(**options))


def test_a_worker_of_a_run_side_by_side_gives_way_to_what_he_is_using(tmp_path):
    done = run_pytest_in(_repo(tmp_path, _SAYS_IT_RUNS_BELOW_NORMAL), "-n", "1")

    assert done.returncode == 0, done.stdout + done.stderr


def test_a_run_that_stops_at_its_first_failure_deals_its_workers_few_tests_at_a_time():
    config = _controller(numprocesses=8, maxfail=1, maxschedchunk=None)

    worker_processes.pytest_configure(config)

    assert config.option.maxschedchunk == worker_processes.TESTS_DEALT_AT_A_TIME_WHEN_STOPPING_AT_A_FAILURE


def test_a_run_that_goes_on_past_failures_is_dealt_as_the_workers_plugin_chooses():
    config = _controller(numprocesses=8, maxfail=0, maxschedchunk=None)

    worker_processes.pytest_configure(config)

    assert config.option.maxschedchunk is None


def test_a_deal_the_run_asked_for_stands():
    config = _controller(numprocesses=8, maxfail=1, maxschedchunk=50)

    worker_processes.pytest_configure(config)

    assert config.option.maxschedchunk == 50


def test_a_clock_given_the_computer_ends_the_test_at_its_ceiling():
    ended = []
    clock = worker_processes.StarvedClock(0.05, lambda: ended.append(True), tick=0.005, idle_share=lambda: 1.0)

    clock.start()
    clock.join(30)

    assert ended == [True]


def _wakes_until_the_ceiling(idle: float) -> int:
    wakes = []
    clock = worker_processes.StarvedClock(10 * 2**-7, lambda: None, tick=2**-7,
                                          idle_share=lambda: wakes.append(True) or idle)
    clock.start()
    clock.join(5)
    return len(wakes)


def test_on_a_computer_with_processors_to_spare_the_ceiling_is_its_seconds():
    assert _wakes_until_the_ceiling(idle=1.0) == 10


def test_a_computer_whose_processors_are_all_busy_starves_the_worker_so_its_seconds_count_less():
    assert _wakes_until_the_ceiling(idle=0.0) == 10 / worker_processes.StarvedClock.LEAST_SHARE_COUNTED


def test_a_clock_stopped_with_its_test_ends_nothing():
    ended = []
    clock = worker_processes.StarvedClock(5.0, lambda: ended.append(True), tick=0.005)

    clock.start()
    clock.stop()

    assert ended == []
    assert not clock.is_alive()


def _a_test_in(config) -> Namespace:
    return Namespace(config=config)


def test_a_run_in_one_process_keeps_the_ceiling_pytest_timeout_sets():
    settings = Namespace(method="thread", timeout=5.0)

    assert worker_processes.pytest_timeout_set_timer(_a_test_in(_controller()), settings) is None


def test_a_worker_sets_a_ceiling_its_test_stops_when_it_ends():
    expired = []
    timeout_plugin = Namespace(timeout_timer=lambda item, settings: expired.append(item))
    worker = Namespace(workerinput={}, pluginmanager=Namespace(getplugin=lambda name: timeout_plugin))
    test = _a_test_in(worker)

    assert worker_processes.pytest_timeout_set_timer(test, Namespace(method="thread", timeout=60.0))
    test.cancel_timeout()

    assert expired == []


def test_each_thread_s_stack_in_a_timeout_s_report_is_headed_by_its_name():
    stacks = worker_processes._Stacks()

    stacks.sep("~", title="Stack of MainThread (1)")

    assert stacks.getvalue() == "~~~~ Stack of MainThread (1) ~~~~\n"


def test_the_share_of_the_computer_left_idle_is_read_as_a_fraction():
    idle_share = worker_processes._IdleShare()
    time.sleep(0.05)

    assert 0.0 <= idle_share() <= 1.0


_HANGS = """\
import time


def test_it_hangs():
    time.sleep(120)
"""


_LOOKS_FOR_ITS_CEILING = """\
import threading


def test_its_ceiling_counts_the_computers_spare_time():
    assert "app_support hang ceiling" in [thread.name for thread in threading.enumerate()]
"""


def test_a_worker_s_ceiling_is_the_one_that_counts_the_computer_s_spare_time(tmp_path):
    done = run_pytest_in(_repo(tmp_path, _LOOKS_FOR_ITS_CEILING), "-n", "1", "--timeout=60",
                         "--timeout-method=thread")

    assert done.returncode == 0, done.stdout + done.stderr


def test_a_hang_in_a_worker_is_still_ended_at_its_ceiling(tmp_path):
    done = run_pytest_in(_repo(tmp_path, _HANGS), "-n", "1", "--timeout=2", "--timeout-method=thread")

    assert "FAILED test_it.py::test_it_hangs - Timeout: ran past 2 s" in done.stdout, done.stdout + done.stderr
    assert "time.sleep(120)" in done.stdout


def test_a_run_in_one_process_has_nothing_dealt():
    config = _controller(maxfail=1)

    worker_processes.pytest_configure(config)

    assert not hasattr(config.option, "maxschedchunk")

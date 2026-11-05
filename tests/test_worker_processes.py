from __future__ import annotations

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


def test_a_run_in_one_process_has_nothing_dealt():
    config = _controller(maxfail=1)

    worker_processes.pytest_configure(config)

    assert not hasattr(config.option, "maxschedchunk")

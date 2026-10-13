from __future__ import annotations

import os
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

from app_support import integration_runs
from app_support.integration_runs import RunRecord
from app_support.win32 import process_started

JOINED = datetime(2026, 10, 10, 20, 0, 5).astimezone()


def a_run(**changes) -> RunRecord:
    fields = {"checkout": "crown-colors-1a2b3c", "branch": "claude/crown-colors-1a2b3c", "session": "5e55-10n",
              "what": ["-k", "test_crown_integration"], "short": True, "pid": 4242, "process_started": 1234567,
              "joined": JOINED}
    return RunRecord(**{**fields, **changes})


def test_the_runs_are_written_down_in_the_fun_time_checkouts_state_folder(tmp_path: Path):
    assert integration_runs.runs_dir(tmp_path / "fun_time") == tmp_path / "fun_time" / "state" / "integration_runs"


def test_a_run_written_down_reads_back_as_it_was_written(tmp_path: Path):
    finished = a_run(got_the_machine=JOINED + timedelta(minutes=3), seen=JOINED + timedelta(minutes=9),
                     ended=JOINED + timedelta(minutes=9), exit_code=1)

    integration_runs.write_run(tmp_path, finished)

    assert integration_runs.read_runs(tmp_path) == [finished]


def test_a_run_reads_back_from_the_file_it_was_written_to(tmp_path: Path):
    written_to = integration_runs.write_run(tmp_path, a_run())

    assert integration_runs.read_run(written_to) == a_run()


def test_a_run_read_while_its_record_is_being_replaced_reads_as_it_was_written(tmp_path: Path, being_replaced):
    written_to = integration_runs.write_run(tmp_path, a_run())

    with being_replaced(written_to):
        assert integration_runs.read_run(written_to) == a_run()


def test_a_run_written_down_before_runs_said_whose_session_or_process_they_were_reads_without_them(tmp_path: Path):
    (tmp_path / "20261010-200005-4242.json").write_text(
        '{\n "checkout": "crown-colors-1a2b3c",\n "branch": "claude/crown-colors-1a2b3c",\n'
        ' "what": [],\n "short": false,\n "pid": 4242,\n "joined": "2026-10-10T20:00:05-07:00",\n'
        ' "got_the_machine": "2026-10-10T20:03:05-07:00"\n}', encoding="utf-8")

    [run] = integration_runs.read_runs(tmp_path)

    assert (run.session, run.pid, run.process_started, run.seen, run.ended) == ("", 4242, None, None, None)
    assert run.got_the_machine == datetime.fromisoformat("2026-10-10T20:03:05-07:00")


def test_a_run_written_by_a_newer_fun_time_still_reads_with_what_this_copy_knows(tmp_path: Path):
    path = integration_runs.write_run(tmp_path, a_run())
    path.write_text(path.read_text(encoding="utf-8").replace('"pid"', '"something_new": 7,\n "pid"'), encoding="utf-8")

    assert integration_runs.read_runs(tmp_path) == [a_run()]


def test_a_run_is_still_going_while_the_process_that_wrote_it_runs():
    this_process = a_run(pid=os.getpid(), process_started=process_started(os.getpid()))

    assert integration_runs.still_going(this_process)


def test_a_run_that_wrote_down_its_end_is_over_while_its_process_lingers():
    this_process = a_run(pid=os.getpid(), process_started=process_started(os.getpid()), ended=JOINED, exit_code=0)

    assert not integration_runs.still_going(this_process)


def test_a_run_whose_process_has_ended_is_no_longer_going():
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    try:
        run = a_run(pid=child.pid, process_started=process_started(child.pid))
    finally:
        child.kill()
        child.wait()

    assert run.process_started is not None
    assert not integration_runs.still_going(run)


def test_a_later_process_given_a_finished_runs_number_is_not_that_run():
    started_later = process_started(os.getpid()) + 1

    assert not integration_runs.still_going(a_run(pid=os.getpid(), process_started=started_later))


def test_a_run_that_never_said_when_its_process_started_is_going_while_a_process_older_than_its_joining_has_its_number():
    joined_now = datetime.now().astimezone().replace(microsecond=0)
    joined_before_this_process = joined_now - timedelta(days=1)

    assert integration_runs.still_going(a_run(pid=os.getpid(), process_started=None, joined=joined_now))
    assert not integration_runs.still_going(a_run(pid=os.getpid(), process_started=None,
                                                  joined=joined_before_this_process))


def test_a_file_in_the_folder_that_is_no_run_is_passed_over(tmp_path: Path):
    integration_runs.write_run(tmp_path, a_run())
    (tmp_path / "20261010-200006-1.json").write_text("{not json", encoding="utf-8")
    (tmp_path / "20261010-200007-2.json").write_text('{"checkout": "half"}', encoding="utf-8")

    assert integration_runs.read_runs(tmp_path) == [a_run()]

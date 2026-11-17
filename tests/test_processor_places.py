from __future__ import annotations

import os
import sys
import threading
import uuid
from argparse import Namespace

import pytest

from app_support import processor_places
from app_support.machine_line import SingleInstanceLock, held_elsewhere
from app_support.processor_places import Places
from app_support.threading_utils import wait_until

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="the places are Windows named mutexes")


def _pool(size: int, **patience) -> dict:
    return {"name": rf"Global\app_support_test_places_{uuid.uuid4().hex}", "size": size,
            "says_it_waits_after_s": 0.05, **patience}


class _Run(threading.Thread):
    def __init__(self, pool: dict, wanted: int, *, short: bool = False, order: list | None = None,
                 label: str = "") -> None:
        super().__init__(daemon=True)
        self.places = Places(**pool)
        self.said: list[str] = []
        self.said_something = threading.Event()
        self.got = threading.Event()
        self.done = threading.Event()
        self._wanted, self._short, self._order, self._label = wanted, short, order, label

    def run(self) -> None:
        self.places.take(self._wanted, short=self._short, say=self._say)
        if self._order is not None:
            self._order.append(self._label)
        self.got.set()
        self.done.wait()
        self.places.give_back()

    def _say(self, line: str) -> None:
        self.said.append(line)
        self.said_something.set()

    def ends(self) -> None:
        self.done.set()
        self.join()


def test_runs_the_pool_has_places_for_run_at_once_and_say_nothing():
    pool = _pool(4) | {"says_it_waits_after_s": 3600.0}
    runs = [_Run(pool, 2), _Run(pool, 2)]
    for run in runs:
        run.start()
    try:
        assert all(run.got.wait() for run in runs)
        assert [run.said for run in runs] == [[], []]
    finally:
        for run in runs:
            run.ends()


def _started(*runs: _Run) -> list[_Run]:
    for run in runs:
        run.start()
    return list(runs)


def test_a_run_the_pool_is_short_for_says_so_once_and_runs_when_places_come_back():
    pool = _pool(4)
    holder, = _started(_Run(pool, 3))
    holder.got.wait()
    waiting, = _started(_Run(pool, 2))
    waiting.said_something.wait()
    assert not waiting.got.is_set()
    assert waiting.said == ["Waiting for 2 of this computer's 4 test places, which other runs are using."]

    holder.ends()
    waiting.got.wait()
    waiting.ends()

    assert len(waiting.said) == 2
    assert waiting.said[1].startswith("Got 2 test places after ")


def _waiting(pool: dict, wanted: int, order: list, label: str, *, short: bool = False) -> _Run:
    run, = _started(_Run(pool, wanted, short=short, order=order, label=label))
    run.said_something.wait()
    return run


def test_whole_runs_get_their_places_in_the_order_they_came():
    pool = _pool(2)
    holder, = _started(_Run(pool, 2))
    holder.got.wait()
    order: list[str] = []
    runs = [_waiting(pool, 2, order, str(number)) for number in range(4)]

    assert [run.said[0] for run in runs[1:]] == [
        "Waiting for 2 of this computer's 2 test places: 1 run is ahead of this one in line.",
        "Waiting for 2 of this computer's 2 test places: 2 runs are ahead of this one in line.",
        "Waiting for 2 of this computer's 2 test places: 3 runs are ahead of this one in line."]
    holder.ends()
    for run in runs:
        run.got.wait()
        run.ends()

    assert order == ["0", "1", "2", "3"]


def test_a_one_process_run_takes_a_place_a_whole_run_ahead_of_it_is_still_waiting_for():
    pool = _pool(2)
    holders = _started(_Run(pool, 1), _Run(pool, 1))
    for holder in holders:
        holder.got.wait()
    order: list[str] = []
    whole = _waiting(pool, 2, order, "whole")
    one = _waiting(pool, 1, order, "one", short=True)

    holders[0].ends()
    one.got.wait()
    holders[1].ends()
    one.ends()
    whole.got.wait()
    whole.ends()

    assert order == ["one", "whole"]


def _going_next(pool: dict) -> bool:
    return held_elsewhere(SingleInstanceLock(pool["name"] + "_full_goes_next"))


def test_a_whole_run_that_has_given_way_long_enough_goes_before_one_process_runs():
    pool = _pool(2, full_run_gives_way_s=0, looks_again_every_s=0.05)
    holders = _started(_Run(pool, 1), _Run(pool, 1))
    for holder in holders:
        holder.got.wait()
    order: list[str] = []
    whole = _waiting(pool, 2, order, "whole")
    wait_until(lambda: _going_next(pool))
    one = _waiting(pool, 1, order, "one", short=True)

    for holder in holders:
        holder.ends()
    whole.got.wait()
    whole.ends()
    one.got.wait()
    one.ends()

    assert order == ["whole", "one"]


def test_the_places_of_a_run_that_ended_without_giving_them_back_go_to_the_next_run():
    pool = _pool(2)
    vanished = threading.Thread(target=lambda: Places(**pool).take(2, short=False, say=print))
    vanished.start()
    vanished.join()

    after, = _started(_Run(pool | {"says_it_waits_after_s": 3600.0}, 2))
    after.got.wait()
    after.ends()

    assert after.said == []


def test_a_run_asking_for_more_places_than_the_computer_has_takes_them_all():
    pool = _pool(2)
    greedy, = _started(_Run(pool, 8))
    greedy.got.wait()
    order: list[str] = []
    next_one = _waiting(pool, 1, order, "next", short=True)

    greedy.ends()
    next_one.got.wait()
    next_one.ends()

    assert next_one.said[0] == "Waiting for 1 of this computer's 2 test places, which other runs are using."


def test_a_run_inside_a_process_that_holds_places_is_told_so():
    pool = _pool(2)
    holder, = _started(_Run(pool, 1))
    holder.got.wait()
    try:
        assert Places(**pool).held_by_one_of({os.getpid()})
    finally:
        holder.ends()

    assert not Places(**pool).held_by_one_of({os.getpid()})


class _NoCapture:
    @staticmethod
    def getplugin(_name):
        return None


def _a_run(*, worker: bool = False, **asked):
    option = Namespace(**({"numprocesses": None, "help": False, "collectonly": False} | asked))
    run = Namespace(option=option, stash=pytest.Stash(), pluginmanager=_NoCapture())
    if worker:
        run.workerinput = {}
    return run


@pytest.mark.parametrize(("numprocesses", "places"), [(None, 1), (0, 1), (1, 1), (8, 8)])
def test_a_run_takes_a_place_for_each_process_it_runs_tests_in(numprocesses, places):
    assert processor_places.places_a_run_takes(_a_run(numprocesses=numprocesses).option) == places


def test_a_run_in_one_process_is_a_short_run():
    assert processor_places.is_short(_a_run().option)
    assert not processor_places.is_short(_a_run(numprocesses=8).option)


def test_a_run_on_this_computer_takes_part(monkeypatch):
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)

    assert processor_places.takes_part(_a_run(numprocesses=8), inside_a_run=lambda: False)


@pytest.mark.parametrize("run", [
    _a_run(worker=True), _a_run(help=True), _a_run(collectonly=True)], ids=["worker", "help", "collect-only"])
def test_a_worker_and_a_run_that_runs_no_tests_take_no_part(monkeypatch, run):
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)

    assert not processor_places.takes_part(run, inside_a_run=lambda: False)


def test_a_run_on_githubs_runners_takes_no_part(monkeypatch):
    monkeypatch.setenv("GITHUB_ACTIONS", "true")

    assert not processor_places.takes_part(_a_run(numprocesses=8), inside_a_run=lambda: False)


def test_a_run_a_test_of_another_run_started_takes_no_part(monkeypatch):
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)

    assert not processor_places.takes_part(_a_run(numprocesses=8), inside_a_run=lambda: True)


def test_a_run_waits_for_its_places_before_its_tests_and_gives_them_back_after(monkeypatch, capsys):
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    pool = _pool(2)
    holder, = _started(_Run(pool, 2))
    holder.got.wait()
    run = _a_run(numprocesses=2)
    configured = threading.Thread(target=processor_places.take_for_the_run, args=(run, Places(**pool)))
    configured.start()
    wait_until(lambda: "Waiting" in capsys.readouterr().err)
    holder.ends()
    configured.join()

    processor_places.give_back_after_the_run(run)

    after, = _started(_Run(pool | {"says_it_waits_after_s": 3600.0}, 2))
    after.got.wait()
    after.ends()
    assert after.said == []


def test_a_run_no_process_above_it_holds_places_for_is_not_inside_one():
    assert not processor_places.inside_a_run_holding(Places(**_pool(1)))


def test_a_worker_starting_and_ending_takes_and_gives_back_nothing():
    worker = _a_run(worker=True, numprocesses=8)

    processor_places.pytest_configure(worker)
    processor_places.pytest_unconfigure(worker)

    assert len(worker.stash) == 0

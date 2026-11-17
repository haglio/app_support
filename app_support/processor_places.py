from __future__ import annotations

import contextlib
import os
import sys
import threading
import time
from collections.abc import Callable

import pytest

from app_support import processes
from app_support.machine_line import (
    THE_NAMESPACE_EVERY_LOGIN_SESSION_SHARES,
    Lane,
    SingleInstanceLock,
    first_taken,
    held_elsewhere,
)

THIS_COMPUTERS_PLACES = f"{THE_NAMESPACE_EVERY_LOGIN_SESSION_SHARES}haglio_test_processor_place"
FULL_RUN_GIVES_WAY_S = 5 * 60
LOOKS_AGAIN_EVERY_S = 1.0
SAYS_IT_WAITS_AFTER_S = 1.0


def waiting_line(wanted: int, size: int, ahead: int) -> str:
    asked = f"Waiting for {wanted} of this computer's {size} test places"
    if not ahead:
        return f"{asked}, which other runs are using."
    return f"{asked}: {ahead} run{' is' if ahead == 1 else 's are'} ahead of this one in line."


def how_long(seconds: float) -> str:
    minutes, seconds = divmod(round(seconds), 60)
    return f"{minutes} min {seconds} s" if minutes else f"{seconds} s"


class Places:
    def __init__(self, *, name: str = THIS_COMPUTERS_PLACES, size: int | None = None,
                 full_run_gives_way_s: float = FULL_RUN_GIVES_WAY_S,
                 looks_again_every_s: float = LOOKS_AGAIN_EVERY_S,
                 says_it_waits_after_s: float = SAYS_IT_WAITS_AFTER_S) -> None:
        self._size = size or os.cpu_count() or 1
        self._names = [f"{name}_{number}" for number in range(self._size)]
        self._places = [SingleInstanceLock(name) for name in self._names]
        self._name = name
        self._held_by_this_process = self._held_by(os.getpid())
        self._lanes = {True: f"{name}_short_lane", False: f"{name}_full_lane"}
        self._full_goes_next = SingleInstanceLock(f"{name}_full_goes_next")
        self._a_one_process_run_takes_a_place = SingleInstanceLock(self._lanes[True])
        self._gives_way_s, self._looks_again_every_s = full_run_gives_way_s, looks_again_every_s
        self._says_it_waits_after_s = says_it_waits_after_s
        self._taken: list[SingleInstanceLock] = []

    def take(self, wanted: int, *, short: bool, say: Callable[[str], None]) -> None:
        wanted = min(wanted, self._size)
        began = time.monotonic()
        self._held_by_this_process.acquire(timeout=0)
        lane = Lane(self._lanes[short])
        lane.join()
        said_it_waits = threading.Event()

        def say_it_waits() -> None:
            say(waiting_line(wanted, self._size, lane.runs_ahead()))
            said_it_waits.set()

        waiting = threading.Timer(self._says_it_waits_after_s, say_it_waits)
        waiting.start()
        try:
            lane.wait_for_the_front()
            self._gather(wanted, short=short, at_the_head=time.monotonic())
        finally:
            waiting.cancel()
            waiting.join()
            lane.leave()
            self._full_goes_next.close()
        if said_it_waits.is_set():
            say(f"Got {wanted} test places after {how_long(time.monotonic() - began)} in line.")

    def _gather(self, wanted: int, *, short: bool, at_the_head: float) -> None:
        going_next = False
        while len(self._taken) < wanted:
            if short and held_elsewhere(self._full_goes_next):
                with self._full_goes_next:
                    pass
            if not short and not going_next and time.monotonic() - at_the_head >= self._gives_way_s:
                going_next = self._full_goes_next.acquire(timeout=0)
            free = [place for place in self._places if place not in self._taken]
            taken = first_taken(free, timeout=self._looks_again_every_s)
            if taken is None:
                continue
            if not short and not going_next and held_elsewhere(self._a_one_process_run_takes_a_place):
                taken.release()
                if self._a_one_process_run_takes_a_place.acquire(timeout=self._looks_again_every_s):
                    self._a_one_process_run_takes_a_place.release()
                continue
            self._taken.append(taken)

    def give_back(self) -> None:
        for place in self._taken:
            place.close()
        self._taken = []
        self._held_by_this_process.close()

    def held_by_one_of(self, pids: set[int]) -> bool:
        return any(held_elsewhere(self._held_by(pid)) for pid in pids)

    def _held_by(self, pid: int) -> SingleInstanceLock:
        return SingleInstanceLock(f"{self._name}_held_by_{pid}")


def places_a_run_takes(option) -> int:
    return max(getattr(option, "numprocesses", None) or 0, 1)


def is_short(option) -> bool:
    return places_a_run_takes(option) == 1


def inside_a_run_holding(places: Places) -> bool:
    among = {process.pid: process for process in processes.running()}
    return places.held_by_one_of(processes.this_process_and_its_parents(among) - {os.getpid()})


def takes_part(config, *, inside_a_run: Callable[[], bool]) -> bool:
    return not (hasattr(config, "workerinput") or sys.platform != "win32"
                or os.environ.get("GITHUB_ACTIONS") == "true"
                or config.option.help or config.option.collectonly or inside_a_run())


_PLACES = pytest.StashKey[Places]()


def _said_to_whoever_runs_it(config, line: str) -> None:
    capture = config.pluginmanager.getplugin("capturemanager")
    with capture.global_and_fixture_disabled() if capture else contextlib.nullcontext():
        print(line, file=sys.stderr, flush=True)


def take_for_the_run(config, places: Places) -> None:
    if takes_part(config, inside_a_run=lambda: inside_a_run_holding(places)):
        config.stash[_PLACES] = places
        places.take(places_a_run_takes(config.option), short=is_short(config.option),
                    say=lambda line: _said_to_whoever_runs_it(config, line))


def give_back_after_the_run(config) -> None:
    places = config.stash.get(_PLACES, None)
    if places is not None:
        places.give_back()


def pytest_configure(config) -> None:
    take_for_the_run(config, Places())


def pytest_unconfigure(config) -> None:
    give_back_after_the_run(config)

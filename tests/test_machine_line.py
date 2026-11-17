from __future__ import annotations

import sys
import threading
import uuid

import pytest

from app_support.machine_line import Lane, SingleInstanceLock, first_taken, held_elsewhere

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="the line is made of Windows named mutexes")


def _unique_name() -> str:
    return rf"Global\app_support_test_line_{uuid.uuid4().hex}"


def _in_a_thread_of_its_own(act) -> dict:
    seen: dict = {}
    thread = threading.Thread(target=lambda: seen.update(act()))
    thread.start()
    thread.join()
    return seen


def test_a_held_lock_is_held_elsewhere_for_every_other_thread():
    name = _unique_name()
    holder = SingleInstanceLock(name)
    assert holder.acquire()
    try:
        seen = _in_a_thread_of_its_own(lambda: {"held": held_elsewhere(SingleInstanceLock(name))})
    finally:
        holder.close()

    assert seen == {"held": True}


def test_a_lock_whose_holder_ended_without_letting_go_goes_to_the_next_caller():
    name = _unique_name()
    _in_a_thread_of_its_own(lambda: {"took": SingleInstanceLock(name).acquire()})

    taker = SingleInstanceLock(name)
    try:
        assert taker.acquire()
    finally:
        taker.close()


def _a_run_in_line(name: str, order: list[int], number: int, joined: threading.Event) -> threading.Thread:
    def run() -> None:
        lane = Lane(name)
        lane.join()
        joined.set()
        lane.wait_for_the_front()
        order.append(number)
        lane.leave()

    thread = threading.Thread(target=run)
    thread.start()
    return thread


def test_a_lane_gives_its_front_to_runs_in_the_order_they_joined():
    name = _unique_name()
    first = Lane(name)
    first.join()
    first.wait_for_the_front()
    order: list[int] = []
    runs = []
    for number in range(5):
        joined = threading.Event()
        runs.append(_a_run_in_line(name, order, number, joined))
        joined.wait()

    first.leave()
    for run in runs:
        run.join()

    assert order == list(range(5))


def _in_line_until(name: str, leave: threading.Event) -> threading.Thread:
    joined = threading.Event()

    def run() -> None:
        lane = Lane(name)
        lane.join()
        joined.set()
        leave.wait()
        lane.leave()

    thread = threading.Thread(target=run)
    thread.start()
    joined.wait()
    return thread


def test_a_run_counts_the_runs_still_in_line_ahead_of_it():
    name = _unique_name()
    leave = threading.Event()
    earlier = [_in_line_until(name, leave) for _ in range(2)]
    lane = Lane(name)
    lane.join()
    try:
        assert lane.runs_ahead() == 2
    finally:
        leave.set()
        for run in earlier:
            run.join()
        lane.leave()



_A_NAMESPACE_WINDOWS_HAS_NOT_GOT = r"NoSuchNamespace\app_support_test_line"


def test_a_lock_windows_will_not_make_says_why():
    with pytest.raises(OSError, match="WinError"):
        SingleInstanceLock(_A_NAMESPACE_WINDOWS_HAS_NOT_GOT).acquire(timeout=0)


def test_a_lane_windows_will_not_number_says_why():
    with pytest.raises(OSError, match="WinError"):
        Lane(_A_NAMESPACE_WINDOWS_HAS_NOT_GOT).join()


class _NoSuchHandle(SingleInstanceLock):
    @property
    def handle(self) -> int:
        return 0


def test_a_wait_windows_refuses_says_why():
    with pytest.raises(OSError, match="WinError"):
        first_taken([_NoSuchHandle(_unique_name())], timeout=0)


def test_a_lane_whose_numbers_another_kind_of_object_holds_the_name_of_says_why():
    name = _unique_name()
    squatter = SingleInstanceLock(f"{name}_numbers")
    assert squatter.acquire(timeout=0)
    try:
        with pytest.raises(OSError, match="WinError"):
            Lane(name).join()
    finally:
        squatter.close()

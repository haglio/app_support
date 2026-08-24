from __future__ import annotations

import functools
import threading
import time

import pytest

from app_support.threading_utils import start_daemon_thread, wait_until


def test_start_daemon_thread_starts_named_daemon_thread():
    ran = threading.Event()

    def worker():
        ran.set()

    thread = start_daemon_thread(target=worker, name="demo-thread")
    thread.join(timeout=1.0)

    assert ran.is_set()
    assert thread.name == "demo-thread"
    assert thread.daemon is True


def test_start_daemon_thread_passes_args_to_target():
    seen: list[tuple[int, int]] = []

    def worker(a: int, b: int):
        seen.append((a, b))

    thread = start_daemon_thread(target=worker, args=(2, 3))
    thread.join(timeout=1.0)

    assert seen == [(2, 3)]


def test_start_daemon_thread_passes_kwargs_to_target():
    seen: list[dict] = []

    def worker(**kwargs):
        seen.append(kwargs)

    thread = start_daemon_thread(target=worker, kwargs={"host": "127.0.0.1"})
    thread.join(timeout=1.0)

    assert seen == [{"host": "127.0.0.1"}]


class _FakeClock:
    """A clock that only moves when the code under test asks to sleep."""

    def __init__(self):
        self.time = 0.0
        self.naps: list[float] = []

    def now(self) -> float:
        return self.time

    def sleep(self, seconds: float) -> None:
        self.naps.append(seconds)
        self.time += seconds


def test_wait_until_returns_without_sleeping_when_the_predicate_is_already_true():
    clock = _FakeClock()

    wait_until(lambda: True, timeout=5.0, now=clock.now, sleep=clock.sleep)

    assert clock.naps == []


def test_wait_until_polls_at_the_given_interval_until_the_predicate_turns_true():
    clock = _FakeClock()
    polls = []

    def ready():
        polls.append(clock.time)
        return len(polls) == 3

    wait_until(ready, timeout=5.0, interval=0.5, now=clock.now, sleep=clock.sleep)

    assert polls == [0.0, 0.5, 1.0]
    assert clock.naps == [0.5, 0.5]


def test_wait_until_raises_a_timeout_error_naming_the_predicate():
    clock = _FakeClock()

    def the_reader_is_bound():
        return False

    with pytest.raises(TimeoutError) as raised:
        wait_until(
            the_reader_is_bound,
            timeout=1.0,
            interval=0.25,
            now=clock.now,
            sleep=clock.sleep,
        )

    assert "the_reader_is_bound" in str(raised.value)


def test_wait_until_never_sleeps_past_the_deadline():
    clock = _FakeClock()

    with pytest.raises(TimeoutError):
        wait_until(lambda: False, timeout=1.0, interval=0.75, now=clock.now, sleep=clock.sleep)

    assert clock.naps == [0.75, 0.25]
    assert clock.time == 1.0


def test_wait_until_names_a_predicate_that_carries_no_name_by_its_repr():
    clock = _FakeClock()
    never = functools.partial(bool, ())

    with pytest.raises(TimeoutError) as raised:
        wait_until(never, timeout=0.5, interval=0.25, now=clock.now, sleep=clock.sleep)

    assert repr(never) in str(raised.value)


def test_wait_until_checks_the_predicate_once_more_when_the_deadline_arrives():
    # The work often finishes during the last nap. A loop that stops looking
    # *at* the deadline rather than *at and after* it turns that into a red.
    clock = _FakeClock()

    def true_at_the_deadline():
        return clock.time >= 1.0

    wait_until(true_at_the_deadline, timeout=1.0, interval=0.5, now=clock.now, sleep=clock.sleep)

    assert clock.time == 1.0


def test_wait_until_waits_on_a_real_thread_with_no_clock_injected():
    finished = threading.Event()

    def worker():
        time.sleep(0.05)
        finished.set()

    start_daemon_thread(target=worker)
    started = time.monotonic()

    wait_until(finished.is_set, timeout=5.0)

    assert finished.is_set()
    assert time.monotonic() - started < 1.0

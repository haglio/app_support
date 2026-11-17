from __future__ import annotations

import pytest

from app_support.wall_clock_waits import waits_in


def _waits(source: str) -> list[str]:
    return [wait.written for wait in waits_in(source)]


def test_a_sleep_is_a_wait_on_the_wall_clock():
    assert _waits("import time\n\n\ndef test():\n    time.sleep(0.5)\n") == ["time.sleep(0.5)"]


@pytest.mark.parametrize("source", [
    "from time import sleep\nsleep(1)\n",
    "from time import sleep as nap\nnap(1)\n",
    "import time as t\nt.sleep(1)\n",
    "import asyncio\nasyncio.sleep(1)\n",
], ids=["imported", "imported as", "module as", "asyncio"])
def test_a_sleep_under_another_name_is_still_one(source: str):
    assert len(_waits(source)) == 1, source


@pytest.mark.parametrize(("source", "written"), [
    ("import time\nstarted = time.monotonic()\n", "time.monotonic()"),
    ("import time\nstamp = time.time()\n", "time.time()"),
    ("from time import perf_counter\nbegan = perf_counter()\n", "perf_counter()"),
    ("import time\nbegan = time.monotonic_ns()\n", "time.monotonic_ns()"),
    ("from datetime import datetime\nmade = datetime.now()\n", "datetime.now()"),
    ("import datetime\nmade = datetime.datetime.utcnow()\n", "datetime.datetime.utcnow()"),
    ("from datetime import date\nday = date.today()\n", "date.today()"),
    ("import time\nwait_until(ready, now=time.monotonic)\n", "time.monotonic"),
    ("import time\nwait_until(ready, sleep=time.sleep)\n", "time.sleep"),
], ids=["monotonic", "time", "perf_counter", "ns", "now", "utcnow", "today", "clock handed on", "sleep handed on"])
def test_a_read_of_the_wall_clock_called_or_handed_on_is_one_wait(source: str, written: str):
    assert _waits(source) == [written]


@pytest.mark.parametrize("source", [
    "wait_until(ready, timeout=10)\n",
    "proc.communicate(timeout=5.0)\n",
    "subprocess.run(command, timeout=60)\n",
    "run_process_tree(command, timeout_s=1)\n",
    "eventually(started, within_s=15)\n",
    "launch(budget_ms=200)\n",
    "ask(patience_seconds=0.5)\n",
    "reap(stale_timeout_s=3)\n",
    "SETTLE_S = 10\n\n\ndef test():\n    wait_until(ready, timeout=SETTLE_S)\n",
    "MINUTE_S = 60\nTO_START_S: float = 2 * MINUTE_S\nwait_until(ready, timeout=TO_START_S)\n",
    "thread.join(5)\n",
    "done.wait(10.0)\n",
    "future.result(30)\n",
    "sock.settimeout(2)\n",
    "QTest.qWait(200)\n",
], ids=["timeout", "communicate", "run", "timeout_s", "within_s", "budget_ms", "patience", "a longer name",
        "a constant of the file", "a constant worked out of others", "join", "wait", "result", "settimeout",
        "qWait"])
def test_a_number_handed_as_a_wait_is_one(source: str):
    assert len(_waits(source)) == 1, source


@pytest.mark.parametrize("source", [
    "proc.wait(timeout=0)\n",
    "make(count=5, duration_s=3)\n",
    "wait_until(ready)\n",
    "wait_until(ready, timeout=budget)\n",
    "from tests.helpers import SETTLE_S\nwait_until(ready, timeout=SETTLE_S)\n",
    "thread.join()\n",
    "done.wait()\n",
    "', '.join(names)\n",
    "rows.get('size', 5)\n",
    "notes.take(prompts, clock=FakeClock(), budget_s=30)\n",
    "ask(gateway, now=lambda: 0.0, sleep=naps.append, patience_s=1.0)\n",
    "raise subprocess.TimeoutExpired(cmd='tool', timeout=1)\n",
], ids=["zero is a look, not a wait", "not a wait's name", "no number", "a number the test was handed",
        "a constant of another module", "join to the end", "wait to the end", "a string's join",
        "a dictionary's get", "on a clock the test hands it", "on a clock and a sleep the test hands it",
        "a timeout that is only told"])
def test_these_hand_no_number_as_a_wait(source: str):
    assert _waits(source) == [], source


@pytest.mark.parametrize("source", [
    "def test(qtbot):\n    qtbot.waitUntil(lambda: shown)\n",
    "def test(qtbot):\n    qtbot.waitUntil(lambda: shown, timeout=3000)\n",
    "def test(qtbot):\n    with qtbot.waitSignal(view.closed):\n        view.close()\n",
    "def test(qtbot):\n    qtbot.waitExposed(view)\n",
    "def test(qtbot):\n    qtbot.wait(20)\n",
], ids=["its own five seconds", "a number of its own, counted once", "a signal", "exposed", "a pause"])
def test_each_wait_of_pytest_qt_is_one_on_the_wall_clock(source: str):
    assert len(_waits(source)) == 1, source


@pytest.mark.parametrize("source", [
    "patch.object(single_instance, '_PATIENCE_SECONDS', 0.5)\n",
    "patch('app.launch.START_TIMEOUT_S', 2)\n",
    "monkeypatch.setattr(launcher, 'WAIT_S', 0.1)\n",
    "monkeypatch.setattr('app.launch.BUDGET_S', 1.0)\n",
], ids=["patch.object", "patch", "setattr", "setattr by path"])
def test_a_wait_of_the_code_patched_to_a_number_is_one(source: str):
    assert len(_waits(source)) == 1, source


def test_a_wait_of_the_code_patched_to_nothing_is_none():
    assert _waits("patch('app.update.UP_BEFORE_AN_UPDATE_WAIT_S', 0.0)\npatch.object(app, 'NAME', 'x')\n") == []


def test_a_number_beside_the_wall_clock_handed_on_is_on_the_wall_too():
    assert _waits("import time\nwait_until(ready, now=time.monotonic, timeout=10)\n") == [
        "time.monotonic", "wait_until(ready, now=time.monotonic, timeout=10)"]


def test_a_sleep_of_something_else_is_none():
    assert _waits("clock = FakeClock()\nclock.sleep(1)\n") == []

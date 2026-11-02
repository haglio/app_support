from __future__ import annotations

import logging
import os
import subprocess
import sys
from pathlib import Path

import pytest

from app_support.peer_watch import (
    DEFAULT_INTERVAL_SECONDS,
    PeerWatch,
    Surroundings,
    clear_stand_down,
    is_stood_down,
    stand_down,
)


@pytest.fixture
def environ(tmp_path):
    return {"LOCALAPPDATA": str(tmp_path)}


class _Clock:
    def __init__(self):
        self.seconds = 0.0

    def __call__(self) -> float:
        return self.seconds

    def advance(self, seconds: float) -> None:
        self.seconds += seconds


def _watch(*, up, launches, environ, clock=None, interval=None):
    kwargs = {}
    if interval is not None:
        kwargs["interval_seconds"] = interval
    return PeerWatch(
        peer_key="Widget",
        is_up=up,
        launch=lambda: launches.append("launched"),
        surroundings=Surroundings(now=clock or _Clock(), environ=environ, **kwargs),
    )



def test_a_key_nobody_stood_down_is_not_stood_down(environ):
    assert is_stood_down("Widget", environ=environ) is False


def test_standing_down_is_remembered(environ):
    stand_down("Widget", environ=environ)

    assert is_stood_down("Widget", environ=environ) is True


def test_clearing_forgets_a_stand_down(environ):
    stand_down("Widget", environ=environ)

    clear_stand_down("Widget", environ=environ)

    assert is_stood_down("Widget", environ=environ) is False


def test_clearing_a_key_that_was_never_stood_down_is_not_an_error(environ):
    clear_stand_down("Widget", environ=environ)

    assert is_stood_down("Widget", environ=environ) is False


def test_one_key_standing_down_says_nothing_about_another(environ):
    stand_down("Widget", environ=environ)

    assert is_stood_down("Gadget", environ=environ) is False


def test_the_marker_lands_under_localappdata(tmp_path, environ):
    stand_down("Widget", environ=environ)

    markers = list(tmp_path.rglob("Widget.txt"))
    assert len(markers) == 1
    assert markers[0].read_text(encoding="utf-8").strip()


def test_a_marker_that_cannot_be_written_does_not_take_the_quit_down(tmp_path):
    blocker = tmp_path / "blocked"
    blocker.write_text("not a directory", encoding="utf-8")

    stand_down("Widget", environ={"LOCALAPPDATA": str(blocker)})

    assert is_stood_down("Widget", environ={"LOCALAPPDATA": str(blocker)}) is False



def test_a_peer_that_is_up_is_left_alone(environ):
    launches: list[str] = []

    _watch(up=lambda: True, launches=launches, environ=environ).tick()

    assert launches == []


def test_a_peer_that_is_gone_is_started(environ):
    launches: list[str] = []

    _watch(up=lambda: False, launches=launches, environ=environ).tick()

    assert launches == ["launched"]


def test_a_peer_that_was_stood_down_is_left_gone(environ):
    launches: list[str] = []
    stand_down("Widget", environ=environ)

    _watch(up=lambda: False, launches=launches, environ=environ).tick()

    assert launches == []


def test_a_stand_down_that_was_cleared_stops_holding_the_peer_down(environ):
    launches: list[str] = []
    stand_down("Widget", environ=environ)
    clear_stand_down("Widget", environ=environ)

    _watch(up=lambda: False, launches=launches, environ=environ).tick()

    assert launches == ["launched"]



def test_the_first_tick_checks_rather_than_waiting_out_an_interval(environ):
    checks: list[str] = []
    clock = _Clock()
    watch = _watch(
        up=lambda: checks.append("asked") or True, launches=[],
        environ=environ, clock=clock, interval=60.0,
    )

    watch.tick()

    assert checks == ["asked"]


def test_ticks_inside_the_interval_do_not_check_again(environ):
    checks: list[str] = []
    clock = _Clock()
    watch = _watch(
        up=lambda: checks.append("asked") or True, launches=[],
        environ=environ, clock=clock, interval=60.0,
    )

    watch.tick()
    clock.advance(59.0)
    watch.tick()

    assert checks == ["asked"]


def test_a_tick_once_the_interval_has_passed_checks_again(environ):
    checks: list[str] = []
    clock = _Clock()
    watch = _watch(
        up=lambda: checks.append("asked") or True, launches=[],
        environ=environ, clock=clock, interval=60.0,
    )

    watch.tick()
    clock.advance(60.0)
    watch.tick()

    assert checks == ["asked", "asked"]


def test_the_default_interval_is_the_shared_one(environ):
    checks: list[str] = []
    clock = _Clock()
    watch = _watch(
        up=lambda: checks.append("asked") or True, launches=[],
        environ=environ, clock=clock,
    )

    watch.tick()
    clock.advance(DEFAULT_INTERVAL_SECONDS - 1)
    watch.tick()
    clock.advance(1)
    watch.tick()

    assert checks == ["asked", "asked"]



def test_a_liveness_check_that_raises_does_not_reach_the_caller(environ, caplog):
    launches: list[str] = []

    def explode():
        raise OSError("the mutex namespace is unavailable")

    with caplog.at_level(logging.ERROR):
        _watch(up=explode, launches=launches, environ=environ).tick()

    assert launches == []
    assert "Peer watch for Widget failed" in caplog.text


def test_a_launcher_that_raises_does_not_reach_the_caller(environ, caplog):
    def explode():
        raise FileNotFoundError("the launcher has been renamed")

    watch = PeerWatch(
        peer_key="Widget", is_up=lambda: False, launch=explode,
        surroundings=Surroundings(now=_Clock(), environ=environ),
    )

    with caplog.at_level(logging.ERROR):
        watch.tick()

    assert "Peer watch for Widget failed" in caplog.text


def test_a_launcher_that_always_fails_is_retried_on_the_interval_not_every_beat(environ):
    attempts: list[str] = []
    clock = _Clock()

    def explode():
        attempts.append("tried")
        raise FileNotFoundError("the launcher has been renamed")

    watch = PeerWatch(
        peer_key="Widget", is_up=lambda: False, launch=explode,
        surroundings=Surroundings(interval_seconds=60.0, now=clock, environ=environ),
    )

    watch.tick()
    for _ in range(20):
        clock.advance(5.0)
        watch.tick()

    assert attempts == ["tried", "tried"]


def test_without_localappdata_the_marker_lands_under_the_home_directory(tmp_path):
    child_environment = {name: value for name, value in os.environ.items() if name != "LOCALAPPDATA"}
    child_environment.update(USERPROFILE=str(tmp_path), HOME=str(tmp_path), PYTHONPATH=str(Path(__file__).parents[1]))
    script = ("from app_support.peer_watch import is_stood_down, stand_down\n"
              "stand_down('Widget', environ={})\n"
              "raise SystemExit(0 if is_stood_down('Widget', environ={}) else 1)")

    ran = subprocess.run([sys.executable, "-c", script], env=child_environment, check=False)

    assert ran.returncode == 0
    assert len(list(tmp_path.rglob("Widget.txt"))) == 1

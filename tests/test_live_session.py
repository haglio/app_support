from __future__ import annotations

import subprocess
import sys
import types
import uuid
from pathlib import Path

import pytest

from app_support import live_session, testing, win32
from app_support.live_session import LIVE_SESSION, holding_a_live_session, is_live

HIS_DESKTOP = "WinSta0\\Default"
A_HIDDEN_DESKTOP = "WinSta0\\ExampleHiddenDesktop"
A_HANDLE = 0x0000_0002_0000_00A4


class _Mutexes:
    def __init__(self, *, held: bool = False) -> None:
        self.held = held
        self.asked: list[str] = []
        self.shared: list[str] = []
        self.released: list[int] = []

    def is_held(self, name: str) -> bool:
        self.asked.append(name)
        return self.held

    def share(self, name: str) -> int:
        self.shared.append(name)
        return A_HANDLE

    def release(self, handle: int) -> None:
        self.released.append(handle)


def _holding(mutexes: _Mutexes, desktop: str, checkout: Path | None = None):
    return holding_a_live_session(desktop=lambda: desktop, checkout=lambda: checkout, share=mutexes.share,
                                  release=mutexes.release)


def test_asking_is_one_look_at_the_live_session_mark():
    mutexes = _Mutexes(held=True)

    assert is_live(is_held=mutexes.is_held) is True
    assert mutexes.asked == [LIVE_SESSION]


def test_with_nobody_holding_the_mark_no_session_is_live():
    assert is_live(is_held=_Mutexes(held=False).is_held) is False


def test_a_session_on_his_desktop_holds_the_mark_until_it_ends():
    mutexes = _Mutexes()

    with _holding(mutexes, HIS_DESKTOP):
        while_live = (list(mutexes.shared), list(mutexes.released))

    assert while_live == ([LIVE_SESSION], [])
    assert mutexes.released == [A_HANDLE]


def test_a_session_that_dies_still_lets_the_mark_go():
    mutexes = _Mutexes()

    with pytest.raises(RuntimeError), _holding(mutexes, HIS_DESKTOP):
        raise RuntimeError("the session died")

    assert mutexes.released == [A_HANDLE]


def test_a_session_on_a_hidden_desktop_is_no_session_of_his():
    mutexes = _Mutexes()

    with _holding(mutexes, A_HIDDEN_DESKTOP):
        pass

    assert (mutexes.shared, mutexes.released) == ([], [])


def _a_checkout(folder: Path, *, worktree: bool) -> Path:
    folder.mkdir()
    (folder / ".git").write_text("gitdir: elsewhere") if worktree else (folder / ".git").mkdir()
    return folder


def test_a_funestra_of_a_preview_holds_nothing_since_only_a_production_one_is_his_session(tmp_path):
    mutexes = _Mutexes()

    with _holding(mutexes, HIS_DESKTOP, _a_checkout(tmp_path / "preview", worktree=True)):
        pass

    assert mutexes.shared == []


def test_a_funestra_of_a_production_checkout_holds_the_mark(tmp_path):
    mutexes = _Mutexes()

    with _holding(mutexes, HIS_DESKTOP, _a_checkout(tmp_path / "production", worktree=False)):
        pass

    assert mutexes.shared == [LIVE_SESSION]


def test_a_mark_windows_would_not_make_is_never_let_go():
    mutexes = _Mutexes()
    mutexes.share = lambda name: None

    with _holding(mutexes, HIS_DESKTOP):
        pass

    assert mutexes.released == []


def test_on_windows_the_mark_reads_live_while_held_and_free_after(monkeypatch):
    monkeypatch.setattr(live_session, "LIVE_SESSION", f"Local\\app-support-test-{uuid.uuid4().hex}")

    with holding_a_live_session(desktop=lambda: HIS_DESKTOP, checkout=lambda: None):
        while_held = is_live()

    assert (while_held, is_live()) == (True, False)


def test_it_imports_where_ctypes_has_no_windows_half_as_the_apps_import_checks_ask():
    without_the_windows_half = ("import ctypes, ctypes.wintypes\n"
                                "for name in ('windll', 'oledll', 'WinDLL', 'OleDLL'):\n"
                                "    if hasattr(ctypes, name):\n"
                                "        delattr(ctypes, name)\n"
                                "import app_support.live_session\n")

    run = subprocess.run([sys.executable, "-c", without_the_windows_half], capture_output=True, text=True,
                         check=False)

    assert run.returncode == 0, run.stderr[-2000:]


def test_a_test_can_have_no_session_live_whoever_holds_the_mark():
    held = win32.share_mutex(LIVE_SESSION)
    try:
        with testing.no_session_live():
            asked_inside = is_live()
    finally:
        win32.release_mutex(held)

    assert asked_inside is False


def test_a_program_started_from_a_checkout_is_found_to_run_from_it(tmp_path, monkeypatch):
    checkout = _a_checkout(tmp_path / "an-app", worktree=True)
    (checkout / "the_app").mkdir()
    monkeypatch.setitem(sys.modules, "__main__", types.SimpleNamespace(__file__=str(checkout / "the_app" / "app.py")))

    assert live_session._checkout_of_this_program() == checkout.resolve()

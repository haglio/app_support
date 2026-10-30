"""Binding a Win32 DLL in a process whose ctypes may have no Windows half."""
from __future__ import annotations

import ctypes
import ctypes.wintypes
from types import SimpleNamespace

import pytest

from app_support import win32_loader


@pytest.fixture
def without_windows(monkeypatch):
    monkeypatch.setattr(win32_loader, "WIN32_AVAILABLE", False)
    return win32_loader


@pytest.fixture
def available(monkeypatch):
    monkeypatch.setattr(win32_loader, "WIN32_AVAILABLE", True)
    return monkeypatch


def test_the_flag_says_whether_this_ctypes_can_bind_a_dll():
    assert win32_loader.WIN32_AVAILABLE is hasattr(ctypes, "windll")


def test_a_call_that_reaches_an_unbound_entry_point_names_it(without_windows):
    user32 = without_windows.load_dll("user32")

    with pytest.raises(win32_loader.Win32Unavailable, match=r"user32\.SetWindowPos"):
        user32.SetWindowPos(0, 0, 0, 0, 0, 0, 0)


def test_an_unbound_entry_point_still_takes_the_argtypes_declared_on_it(without_windows):
    kernel32 = without_windows.load_dll("kernel32")

    kernel32.OpenProcess.argtypes = [ctypes.wintypes.DWORD]
    kernel32.OpenProcess.restype = ctypes.wintypes.HANDLE

    assert kernel32.OpenProcess.argtypes == [ctypes.wintypes.DWORD]
    assert kernel32.OpenProcess.restype is ctypes.wintypes.HANDLE


def test_an_unbound_entry_point_is_the_same_object_every_time(without_windows):
    user32 = without_windows.load_dll("user32")

    assert user32.ShowWindow is user32.ShowWindow


def test_an_unbound_dll_has_no_dunder_entry_points(without_windows):
    user32 = without_windows.load_dll("user32")

    assert not hasattr(user32, "__wrapped__")


def test_an_error_saving_handle_stands_in_the_same_way(without_windows):
    kernel32 = without_windows.load_dll("kernel32", use_last_error=True)

    with pytest.raises(win32_loader.Win32Unavailable, match=r"kernel32\.CreateMutexW"):
        kernel32.CreateMutexW(None, False, "name")


def test_reading_the_last_error_without_a_windows_ctypes_says_so(without_windows):
    with pytest.raises(win32_loader.Win32Unavailable, match="get_last_error"):
        without_windows.get_last_error()


def test_an_unbound_callback_prototype_refuses_to_be_made(without_windows):
    prototype = without_windows.win_functype(ctypes.wintypes.BOOL, ctypes.wintypes.HWND)

    with pytest.raises(win32_loader.Win32Unavailable):
        prototype(lambda hwnd: True)


def test_a_bound_dll_is_the_handle_every_caller_in_the_process_shares(available):
    kernel32 = object()
    available.setattr(ctypes, "windll", SimpleNamespace(kernel32=kernel32), raising=False)

    assert win32_loader.load_dll("kernel32") is kernel32


def test_a_bound_dll_that_saves_the_last_error_is_a_handle_of_its_own(available):
    made = []
    available.setattr(ctypes, "WinDLL", lambda name, **options: made.append((name, options)) or made,
                      raising=False)

    assert win32_loader.load_dll("kernel32", use_last_error=True) is made
    assert made == [("kernel32", {"use_last_error": True})]


def test_a_bound_callback_prototype_is_the_stdcall_one(available):
    available.setattr(ctypes, "WINFUNCTYPE", lambda *types: types, raising=False)

    assert win32_loader.win_functype(ctypes.c_int, ctypes.c_void_p) == (ctypes.c_int, ctypes.c_void_p)


def test_the_last_error_is_the_one_ctypes_saved(available):
    available.setattr(ctypes, "get_last_error", lambda: 5, raising=False)

    assert win32_loader.get_last_error() == 5

"""The Windows calls a windowed process makes about itself.

None of these tests touch Windows.  Each one hands the call under test a fake
DLL through the same keyword-only seam a consumer never uses, so the decisions
-- what is declared, what is passed, what is raised, what is closed -- are
pinned on every platform.  What a fake cannot stand in for is COM itself, and
those cases say so where they stop.
"""
from __future__ import annotations

import ctypes
import pathlib
import uuid

import pytest

from app_support.win32 import (
    _PKEY_AppUserModel_ID,
    is_mutex_held,
    mutex_name,
    read_shortcut_app_user_model_id,
    set_app_user_model_id,
    set_shortcut_app_user_model_id,
    show_error_popup,
    try_acquire_mutex,
)

# One real failure code, as Windows hands it over: a signed 32-bit value whose
# documentation is filed under the unsigned spelling of the same bits.
E_INVALIDARG = -2147024809  # 0x80070057
RPC_E_CHANGED_MODE = -2147417850  # 0x80010106
S_FALSE = 1
ERROR_ALREADY_EXISTS = 183
SYNCHRONIZE = 0x00100000


class _FakeFunction:
    """A ctypes function pointer as far as this module uses one.

    The prototype is settable because declaring it is part of the behaviour
    under test, and every call is recorded because what was passed is the other
    part.
    """

    def __init__(self, result: object = 0, *, name: str = "", log: list | None = None) -> None:
        self.result = result
        self.argtypes: object = None
        self.restype: object = None
        self.calls: list[tuple] = []
        self._name = name
        self._log = log

    def __call__(self, *args):
        self.calls.append(args)
        if self._log is not None:
            self._log.append(self._name)
        return self.result


class _FakeDll:
    """A loaded DLL as far as this module reaches into one."""

    def __init__(self, **functions: _FakeFunction) -> None:
        for name, function in functions.items():
            setattr(self, name, function)


class TestSetAppUserModelId:
    def test_it_hands_the_id_to_the_shell(self):
        set_id = _FakeFunction()
        shell32 = _FakeDll(SetCurrentProcessExplicitAppUserModelID=set_id)

        set_app_user_model_id("Example.App", shell32=lambda: shell32)

        assert set_id.calls == [("Example.App",)]
        assert set_id.argtypes == [ctypes.c_wchar_p]
        assert set_id.restype is ctypes.c_long

    def test_a_refusal_reaches_the_caller(self):
        # The nine copies this replaces disagreed about this: some raised, some
        # logged, some swallowed. Raising is the only one of the three that
        # leaves the choice with the app.
        shell32 = _FakeDll(
            SetCurrentProcessExplicitAppUserModelID=_FakeFunction(E_INVALIDARG))

        with pytest.raises(OSError):
            set_app_user_model_id("Example.App", shell32=lambda: shell32)

    def test_the_refusal_names_the_call_and_a_number_that_can_be_looked_up(self):
        # 0x{hr:08x} on a signed value prints 0x-7ff8ffa9 for a code whose
        # documentation is filed under 0x80070057.
        shell32 = _FakeDll(
            SetCurrentProcessExplicitAppUserModelID=_FakeFunction(E_INVALIDARG))

        with pytest.raises(OSError) as raised:
            set_app_user_model_id("Example.App", shell32=lambda: shell32)

        assert "SetCurrentProcessExplicitAppUserModelID" in str(raised.value)
        assert "0x80070057" in str(raised.value)


def _guid_to_uuid(guid) -> uuid.UUID:
    """Read a ``GUID`` struct back out as a UUID.

    Round-tripping is the point: restating the four fields the way the module
    packs them would pass however they were packed.
    """
    return uuid.UUID(fields=(
        guid.Data1, guid.Data2, guid.Data3,
        guid.Data4[0], guid.Data4[1],
        int.from_bytes(bytes(guid.Data4[2:8]), "big"),
    ))


class TestTheShortcutProperty:
    def test_it_is_the_property_the_taskbar_reads(self):
        # The one failure in this module with no HRESULT backing it: a wrong
        # property key writes a real value into the shortcut, reports success,
        # and leaves the second taskbar button this whole module exists to
        # prevent. The key is System.AppUserModel.ID, documented as
        # {9F4C2855-9F79-4B39-A8D0-E1D42DE1D5F3}, 5.
        assert _guid_to_uuid(_PKEY_AppUserModel_ID.fmtid) == uuid.UUID(
            "9f4c2855-9f79-4b39-a8d0-e1d42de1d5f3")
        assert _PKEY_AppUserModel_ID.pid == 5


class _FakeOle32:
    """ole32 as far as the stamper reaches into it.

    The apartment pair, and the one COM call that can refuse before any vtable
    is walked -- which is as far as a fake can go.  Past ``CoCreateInstance``
    the code is reading function pointers out of an object Windows built, and
    only the windows-latest gate can say whether it reads them right.
    """

    def __init__(self, *, init: int = 0, create: int = E_INVALIDARG) -> None:
        self.CoInitializeEx = _FakeFunction(init)
        self.CoUninitialize = _FakeFunction(None)
        self.CoCreateInstance = _FakeFunction(create)


class TestSetShortcutAppUserModelId:
    def test_an_apartment_it_never_opened_is_not_given_back(self):
        # RPC_E_CHANGED_MODE means somebody else put this thread in the other
        # concurrency model and holds the reference. Uninitialising anyway
        # decrements their count and can close the apartment under them.
        ole32 = _FakeOle32(init=RPC_E_CHANGED_MODE)

        with pytest.raises(OSError) as raised:
            set_shortcut_app_user_model_id("C:/pins/Example.lnk", "Example.App",
                                           ole32=lambda: ole32)

        assert ole32.CoUninitialize.calls == []
        assert ole32.CoCreateInstance.calls == []
        assert "CoInitializeEx" in str(raised.value)
        assert "0x80010106" in str(raised.value)

    def test_an_apartment_it_opened_is_given_back_even_when_the_stamp_fails(self):
        ole32 = _FakeOle32(init=0, create=E_INVALIDARG)

        with pytest.raises(OSError) as raised:
            set_shortcut_app_user_model_id("C:/pins/Example.lnk", "Example.App",
                                           ole32=lambda: ole32)

        assert len(ole32.CoUninitialize.calls) == 1
        assert "CoCreateInstance" in str(raised.value)

    def test_an_apartment_the_thread_already_had_is_still_given_back(self):
        # S_FALSE: this thread was already initialised in the same model. It is
        # a success, and it still took a reference this thread owes back.
        ole32 = _FakeOle32(init=S_FALSE, create=E_INVALIDARG)

        with pytest.raises(OSError):
            set_shortcut_app_user_model_id("C:/pins/Example.lnk", "Example.App",
                                           ole32=lambda: ole32)

        assert len(ole32.CoCreateInstance.calls) == 1
        assert len(ole32.CoUninitialize.calls) == 1


class TestReadShortcutAppUserModelId:
    def test_an_apartment_it_never_opened_is_not_given_back(self):
        # The reader's bracket is the stamper's, for the stamper's reason.
        ole32 = _FakeOle32(init=RPC_E_CHANGED_MODE)

        with pytest.raises(OSError) as raised:
            read_shortcut_app_user_model_id("C:/pins/Example.lnk", ole32=lambda: ole32)

        assert ole32.CoUninitialize.calls == []
        assert ole32.CoCreateInstance.calls == []
        assert "CoInitializeEx" in str(raised.value)

    def test_an_apartment_it_opened_is_given_back_even_when_the_read_fails(self):
        ole32 = _FakeOle32(init=0, create=E_INVALIDARG)

        with pytest.raises(OSError) as raised:
            read_shortcut_app_user_model_id("C:/pins/Example.lnk", ole32=lambda: ole32)

        assert len(ole32.CoUninitialize.calls) == 1
        assert "CoCreateInstance" in str(raised.value)


def _a_shortcut(tmp_path: pathlib.Path) -> pathlib.Path:
    """A real .lnk, written the way the family's launchers write theirs --
    through WScript.Shell, which carries no AppUserModelID.  The paths ride in
    as environment variables rather than interpolated into the script, so a
    quote in a temp path is never PowerShell syntax."""
    import os
    import subprocess

    lnk = tmp_path / "Example.lnk"
    script = (
        "$ws = New-Object -ComObject WScript.Shell; "
        "$s = $ws.CreateShortcut($env:LNK_PATH); "
        "$s.TargetPath = $env:LNK_TARGET; "
        "$s.Save()"
    )
    subprocess.run(
        ["powershell.exe", "-NoProfile", "-Command", script],
        check=True, capture_output=True,
        env={**os.environ, "LNK_PATH": str(lnk),
             "LNK_TARGET": os.environ.get("COMSPEC", "cmd.exe")},
    )
    assert lnk.is_file()
    return lnk


@pytest.mark.skipif(not hasattr(ctypes, "windll"), reason="COM: only Windows can say")
class TestTheStampOnARealShortcut:
    """The one thing the fakes above cannot stand in for: past CoCreateInstance
    the code reads function pointers out of an object Windows built, and only
    Windows can say whether it reads them right."""

    def test_a_shortcut_the_shell_wrote_carries_no_identity(self, tmp_path: pathlib.Path):
        assert read_shortcut_app_user_model_id(str(_a_shortcut(tmp_path))) is None

    def test_what_was_stamped_is_what_reads_back(self, tmp_path: pathlib.Path):
        lnk = _a_shortcut(tmp_path)

        set_shortcut_app_user_model_id(str(lnk), "Example.App")

        assert read_shortcut_app_user_model_id(str(lnk)) == "Example.App"

    def test_a_second_stamp_replaces_the_first(self, tmp_path: pathlib.Path):
        lnk = _a_shortcut(tmp_path)
        set_shortcut_app_user_model_id(str(lnk), "Example.App")

        set_shortcut_app_user_model_id(str(lnk), "Example.Other")

        assert read_shortcut_app_user_model_id(str(lnk)) == "Example.Other"


class TestMutexName:
    def test_the_name_is_the_base_and_a_digest_of_the_identity(self):
        # Pinned to the digit, because the name is a promise to a process that
        # is already running: a different spelling of it does not refuse the
        # second launch, it lets it through beside the first.
        assert mutex_name("Global\\ExampleApp", "C:/Example App/example_config.json") \
            == "Global\\ExampleApp.dce3a7c5ad9e"

    def test_a_different_identity_gets_a_different_mutex(self):
        # What buys a suite its own instances: a run on its own temp config is
        # a different session and must not be refused by the live one.
        first = mutex_name("Global\\ExampleApp", "C:/Example App/example_config.json")
        second = mutex_name("Global\\ExampleApp", "C:/Example App/other_config.json")

        assert first != second
        assert second == "Global\\ExampleApp.55654890faf8"

    def test_an_identity_that_is_a_path_spells_the_same_name_twice(self):
        # The callers hand this a Path as often as a string.
        config = pathlib.Path("C:/Example App/example_config.json")

        assert mutex_name("Global\\ExampleApp", config) \
            == mutex_name("Global\\ExampleApp", config)


class _FakeKernel32:
    """kernel32 as far as the mutex guard reaches into it."""

    def __init__(self, *, handle: int = 0, opened: int = 0,
                 log: list | None = None) -> None:
        self.CreateMutexW = _FakeFunction(handle, name="CreateMutexW", log=log)
        self.OpenMutexW = _FakeFunction(opened, name="OpenMutexW", log=log)
        self.CloseHandle = _FakeFunction(1, name="CloseHandle", log=log)


# A handle wider than the 32 bits an undeclared ctypes return would carry it
# back in. Windows hands out low values most of the time, which is why the
# three copies this replaces got away with saying nothing.
WIDE_HANDLE = 0x0000_0002_0000_00A4


class TestTryAcquireMutex:
    def test_the_handle_comes_back_so_the_caller_can_hold_it(self):
        # Returning a bool instead is a live defect in one of the three copies
        # this replaces: the handle it made goes out of scope, and a guard whose
        # handle has been closed stops guarding.
        kernel32 = _FakeKernel32(handle=WIDE_HANDLE)

        held = try_acquire_mutex("Global\\ExampleApp.dce3a7c5ad9e",
                                 kernel32=lambda: kernel32, last_error=lambda: 0)

        assert held == WIDE_HANDLE
        assert kernel32.CreateMutexW.calls == [
            (None, False, "Global\\ExampleApp.dce3a7c5ad9e")]

    def test_the_handle_is_not_closed_out_from_under_the_caller(self):
        kernel32 = _FakeKernel32(handle=WIDE_HANDLE)

        try_acquire_mutex("Global\\ExampleApp.dce3a7c5ad9e",
                          kernel32=lambda: kernel32, last_error=lambda: 0)

        assert kernel32.CloseHandle.calls == []

    def test_the_handle_is_declared_wide_enough_to_come_back_whole(self):
        # An undeclared ctypes return is c_int: a 64-bit handle arrives
        # truncated, CloseHandle then fails to close it, and a handle whose low
        # 32 bits are zero reads as "another instance holds it".
        kernel32 = _FakeKernel32(handle=WIDE_HANDLE)

        try_acquire_mutex("Global\\ExampleApp.dce3a7c5ad9e",
                          kernel32=lambda: kernel32, last_error=lambda: 0)

        assert kernel32.CreateMutexW.restype is ctypes.c_void_p

    def test_a_mutex_someone_else_holds_is_given_back_rather_than_leaked(self):
        # CreateMutexW succeeds either way; ERROR_ALREADY_EXISTS is the only
        # thing that tells the two apart, which is why the handle is opened
        # with use_last_error.
        kernel32 = _FakeKernel32(handle=WIDE_HANDLE)

        held = try_acquire_mutex("Global\\ExampleApp.dce3a7c5ad9e",
                                 kernel32=lambda: kernel32,
                                 last_error=lambda: ERROR_ALREADY_EXISTS)

        assert held is None
        assert kernel32.CloseHandle.calls == [(WIDE_HANDLE,)]

    def test_nothing_runs_between_the_claim_and_the_answer_to_it(self):
        # ERROR_ALREADY_EXISTS is the only thing that tells "I made this mutex"
        # from "I opened somebody else's", and it survives exactly as long as
        # the next call through this handle. use_last_error keeps Python's own
        # runtime out of that gap; keeping this module's other Win32 calls out
        # of it is this module's own job. Declaring a prototype in the gap is
        # safe and this does not claim otherwise -- a lookup writes the thread's
        # error code, never the private one ctypes saved for us -- but a second
        # call does clobber it, and one is a plausible edit away.
        log: list[str] = []
        kernel32 = _FakeKernel32(handle=WIDE_HANDLE, log=log)

        try_acquire_mutex("Global\\ExampleApp.dce3a7c5ad9e",
                          kernel32=lambda: kernel32,
                          last_error=lambda: log.append("read the error") or 0)

        assert log == ["CreateMutexW", "read the error"]

    def test_a_refusal_to_make_the_mutex_at_all_is_not_a_second_instance(self):
        kernel32 = _FakeKernel32(handle=0)

        assert try_acquire_mutex("Global\\ExampleApp.dce3a7c5ad9e",
                                 kernel32=lambda: kernel32, last_error=lambda: 0) is None
        assert kernel32.CloseHandle.calls == []


class TestIsMutexHeld:
    def test_a_held_mutex_is_opened_and_let_go_again(self):
        # Opening rather than creating is the point: a created-then-closed
        # handle would, for those few microseconds, make a starting instance
        # believe another one was already up.
        kernel32 = _FakeKernel32(opened=WIDE_HANDLE)

        assert is_mutex_held("Global\\ExampleApp.dce3a7c5ad9e",
                             kernel32=lambda: kernel32) is True
        assert kernel32.OpenMutexW.calls == [
            (SYNCHRONIZE, False, "Global\\ExampleApp.dce3a7c5ad9e")]
        assert kernel32.CreateMutexW.calls == []
        assert kernel32.CloseHandle.calls == [(WIDE_HANDLE,)]

    def test_a_free_name_is_left_exactly_as_it_was_found(self):
        kernel32 = _FakeKernel32(opened=0)

        assert is_mutex_held("Global\\ExampleApp.dce3a7c5ad9e",
                             kernel32=lambda: kernel32) is False
        assert kernel32.CreateMutexW.calls == []
        assert kernel32.CloseHandle.calls == []


# The four flags, from the documentation rather than from the module under test.
MB_OK = 0x0
MB_ICONERROR = 0x10
MB_SETFOREGROUND = 0x00010000
MB_TOPMOST = 0x00040000


@pytest.mark.skipif(not hasattr(ctypes, "windll"), reason="a named mutex: only Windows can say")
class TestANamedMutexOnWindows:
    """The fakes above pin what is declared and what is closed; these ask
    Windows itself whether the two calls agree about one real mutex, under a
    name nothing else on the machine could be holding."""

    def _close(self, handle: int) -> None:
        kernel32 = ctypes.WinDLL("kernel32")
        kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
        kernel32.CloseHandle(handle)

    def test_a_name_nobody_holds_reads_as_free(self):
        assert not is_mutex_held(f"Local\\app-support-test-{uuid.uuid4().hex}")

    def test_a_held_name_reads_as_held_until_its_handle_closes(self):
        name = f"Local\\app-support-test-{uuid.uuid4().hex}"
        handle = try_acquire_mutex(name)
        assert handle is not None
        try:
            assert is_mutex_held(name)
            assert try_acquire_mutex(name) is None
        finally:
            self._close(handle)
        assert not is_mutex_held(name)

    def test_probing_a_free_name_does_not_claim_it(self):
        # A probe that left a mutex in place would refuse the very instance it
        # was asked on behalf of.
        name = f"Local\\app-support-test-{uuid.uuid4().hex}"

        is_mutex_held(name)

        handle = try_acquire_mutex(name)
        assert handle is not None
        self._close(handle)


class TestShowErrorPopup:
    def test_the_dialog_comes_up_in_front_of_whatever_is_there(self):
        # The reason the whole helper exists. A process launched hidden from a
        # shortcut has no claim on the foreground, so without SETFOREGROUND and
        # TOPMOST the dialog opens *underneath* what the user is looking at -- which
        # reads as having crashed with no explanation. Two of the four copies
        # this replaces omit TOPMOST, which is the flag their own docstring
        # calls the point.
        user32 = _FakeDll(MessageBoxW=_FakeFunction(1))

        show_error_popup("Example App", "The scene file could not be read.",
                         user32=lambda: user32)

        (_, _, _, flags), = user32.MessageBoxW.calls
        assert flags == MB_OK | MB_ICONERROR | MB_SETFOREGROUND | MB_TOPMOST

    def test_the_message_goes_in_the_body_and_the_title_on_the_bar(self):
        # MessageBoxW takes the body first and the caption second, which is the
        # opposite order to the one this is called in.
        user32 = _FakeDll(MessageBoxW=_FakeFunction(1))

        show_error_popup("Example App", "The scene file could not be read.",
                         user32=lambda: user32)

        (hwnd, body, caption, _), = user32.MessageBoxW.calls
        assert hwnd is None
        assert body == "The scene file could not be read."
        assert caption == "Example App"

    def test_a_dialog_that_will_not_open_is_not_raised_over(self):
        # Alone in this module, and deliberately: this is the last thing a dying
        # process does, and an exception thrown from the error reporter replaces
        # the error nobody has been shown yet with one nobody will see either.
        user32 = _FakeDll(MessageBoxW=_FakeFunction(0))

        assert show_error_popup("Example App", "The scene file could not be read.",
                                user32=lambda: user32) is None

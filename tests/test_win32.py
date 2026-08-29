"""The Windows calls a windowed process makes about itself.

None of these tests touch Windows.  Each one hands the call under test a fake
DLL through the same keyword-only seam a consumer never uses, so the decisions
-- what is declared, what is passed, what is raised, what is closed -- are
pinned on every platform.  What a fake cannot stand in for is COM itself, and
those cases say so where they stop.
"""
from __future__ import annotations

import ctypes
import uuid

import pytest

from app_support.win32 import (
    _PKEY_AppUserModel_ID,
    set_app_user_model_id,
    set_shortcut_app_user_model_id,
)

# One real failure code, as Windows hands it over: a signed 32-bit value whose
# documentation is filed under the unsigned spelling of the same bits.
E_INVALIDARG = -2147024809  # 0x80070057
RPC_E_CHANGED_MODE = -2147417850  # 0x80010106
S_FALSE = 1


class _FakeFunction:
    """A ctypes function pointer as far as this module uses one.

    The prototype is settable because declaring it is part of the behaviour
    under test, and every call is recorded because what was passed is the other
    part.
    """

    def __init__(self, result: object = 0) -> None:
        self.result = result
        self.argtypes: object = None
        self.restype: object = None
        self.calls: list[tuple] = []

    def __call__(self, *args):
        self.calls.append(args)
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
        # The one failure in this module with no HRESULT behind it: a wrong
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

"""The Windows calls a windowed process makes about itself.

None of these tests touch Windows.  Each one hands the call under test a fake
DLL through the same keyword-only seam a consumer never uses, so the decisions
-- what is declared, what is passed, what is raised, what is closed -- are
pinned on every platform.  What a fake cannot stand in for is COM itself, and
those cases say so where they stop.
"""
from __future__ import annotations

import ctypes

import pytest

from app_support.win32 import set_app_user_model_id

# One real failure code, as Windows hands it over: a signed 32-bit value whose
# documentation is filed under the unsigned spelling of the same bits.
E_INVALIDARG = -2147024809  # 0x80070057


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

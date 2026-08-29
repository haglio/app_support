"""What a windowed Python process on Windows has to say about itself.

Nothing here knows anything about an application's subject matter.  These are
the Win32 jobs a windowed process does *about itself*, which every app in a
family ends up doing and had all grown its own spelling of:

  * **claiming a taskbar identity.**  Windows groups taskbar buttons by
    AppUserModelID, and takes the icon and the name from whichever pinned
    shortcut carries the same one.  A process that never claims one is given an
    identity derived from its executable -- which for a family of apps sharing
    one interpreter means they land under whatever unrelated application
    registered that path first, wearing its icon and its name.

Every call raises ``OSError`` when Windows refuses, and none of them decide what
that means: an app that cannot group its taskbar button is still an app that
runs, while an app that cannot claim its single-instance mutex must not.  Each
caller keeps the ``try``/``except`` that says which of those it is.

Nothing Windows-only is looked up while this module is imported.  ``WinDLL`` and
the rest of the Windows half of ``ctypes`` exist only on Windows, and this
package installs into every app's venv -- including on the machine a developer
collects a suite on.  Each call loads what it needs when it is called, through a
keyword-only seam a test hands a fake to and no consumer ever passes.
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes


def _load(name: str):
    """The one line only Windows can run: open a system DLL.

    ``use_last_error`` makes ctypes save and restore the per-thread error code
    around every call through this handle, so ``ctypes.get_last_error()`` reads
    what the call set rather than whatever ran next -- Python's own runtime, or
    a DLL injected into the process that calls Win32 functions of its own inside
    a hook.  It costs nothing on the calls that never read it.
    """
    return ctypes.WinDLL(name, use_last_error=True)


def _shell32():
    return _load("shell32")


def _declare(dll, name: str, restype, *argtypes):
    """Give *dll*'s *name* an explicit prototype, and hand the function back.

    ctypes will convert a Python ``str`` and read a C ``int`` back without being
    told, which is why most of the copies this module replaces never said
    anything.  But an undeclared return is ``c_int`` by luck rather than by
    declaration -- a handle is twice that wide, and comes back truncated -- and
    an undeclared argument is converted by the value's Python type rather than
    by the parameter's C one.  Saying it makes the call mean the same thing on
    every build, and makes the wrong argument an error here instead of a fault
    inside Windows.
    """
    function = getattr(dll, name)
    function.argtypes = list(argtypes)
    function.restype = restype
    return function


def _hresult(call: str, hr: int) -> OSError:
    """The failure of *call*, spelled the way its HRESULT is written down.

    ``0x{hr:08x}`` on a signed value prints ``0x-7ffefefa`` for the ``0x80010106``
    a reader would look up.  These failures are the ones nobody can reproduce on
    demand, so the message is the whole record.
    """
    return OSError(f"{call} failed: HRESULT 0x{hr & 0xFFFFFFFF:08x}")


def set_app_user_model_id(app_id: str, *, shell32=_shell32) -> None:
    """Claim *app_id* as this process's taskbar identity.

    Must run before any window exists: Windows reads the identity as a window is
    created, so a call afterwards leaves the windows already on the bar where
    they were.

    Raises ``OSError`` when Windows refuses.  Callers have treated that as
    cosmetic and carried on, because an icon is never worth failing to start
    over -- but that is their call to make and not this one's.
    """
    set_id = _declare(shell32(), "SetCurrentProcessExplicitAppUserModelID",
                      ctypes.c_long, wintypes.LPCWSTR)
    hr = set_id(app_id)
    if hr < 0:  # the FAILED() macro
        raise _hresult("SetCurrentProcessExplicitAppUserModelID", hr)

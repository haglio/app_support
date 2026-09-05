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
  * **stamping that identity onto a shortcut.**  A ``.lnk`` written by
    ``WScript.Shell`` or by PowerShell carries no ``System.AppUserModel.ID``,
    so clicking the pin starts a process Windows treats as a different
    application, and a second taskbar button opens beside the pin it was
    launched from.  Nothing but COM can write that property.
  * **asking whether it is the only instance**, through a named mutex -- and
    holding the handle that is the answer, because Windows lets the mutex go
    when the last handle to it closes.
  * **putting an error where the user will see it**, for a process that was
    launched hidden and has no console and no window to put one in.

Every call raises ``OSError`` when Windows refuses -- ``show_error_popup``
excepted, which says why at its own docstring -- and none of them decide what
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
import hashlib
import uuid
from ctypes import wintypes
from pathlib import Path


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


def _ole32():
    return _load("ole32")


def _kernel32():
    return _load("kernel32")


def _user32():
    return _load("user32")


def _last_error() -> int:
    """The error code the last call through a ``use_last_error`` handle set.

    Read through a seam of its own because it is not a call on any DLL, and
    because ``ctypes.get_last_error`` is another of the names that exists only
    on Windows.
    """
    return ctypes.get_last_error()


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


# --- Stamping the identity onto a shortcut, through COM ----------------------
#
# Everything from here to the end of ``_set_lnk_aumid`` is the block that two
# repos already run byte-identically -- 136 consecutive lines that ``diff``
# reports no difference in -- carried across as it stands rather than rewritten,
# because only Windows can say whether a change to it is right.  Four things
# were changed and nothing else: the plumbing names took an underscore, so this
# package's public surface stays the six calls above and below; ``ole32`` is
# passed in rather than bound at import; the HRESULT messages go through
# ``_hresult``; and ``set_shortcut_app_user_model_id`` is the copy that reads
# ``CoInitializeEx``'s answer.

_COINIT_APARTMENTTHREADED = 0x2
_CLSCTX_ALL = 0x17


class _GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", ctypes.c_ulong),
        ("Data2", ctypes.c_ushort),
        ("Data3", ctypes.c_ushort),
        ("Data4", ctypes.c_ubyte * 8),
    ]


def _make_guid(s: str) -> _GUID:
    u = uuid.UUID(s)
    return _GUID(u.time_low, u.time_mid, u.time_hi_version,
                 (ctypes.c_ubyte * 8)(*u.bytes[8:]))


class _PROPERTYKEY(ctypes.Structure):
    _fields_ = [("fmtid", _GUID), ("pid", ctypes.c_ulong)]


# ``System.AppUserModel.ID``.  The one failure in this module that Windows
# reports no error for: a wrong key here writes a real value into the shortcut,
# answers S_OK, and leaves the duplicate taskbar button in place.
_PKEY_AppUserModel_ID = _PROPERTYKEY(
    _make_guid("9F4C2855-9F79-4B39-A8D0-E1D42DE1D5F3"), 5
)

_VT_LPWSTR = 31


class _PROPVARIANT(ctypes.Structure):
    _fields_ = [
        ("vt", ctypes.c_ushort),
        ("wReserved1", ctypes.c_ushort),
        ("wReserved2", ctypes.c_ushort),
        ("wReserved3", ctypes.c_ushort),
        ("pwszVal", wintypes.LPWSTR),
        ("_pad", ctypes.c_void_p),
    ]


_CLSID_ShellLink = _make_guid("00021401-0000-0000-C000-000000000046")
_IID_IShellLinkW = _make_guid("000214F9-0000-0000-C000-000000000046")
_IID_IPersistFile = _make_guid("0000010B-0000-0000-C000-000000000046")
_IID_IPropertyStore = _make_guid("886D8EEB-8CF2-4446-8D02-CDBA1DBDCF99")

_STGM_READ = 0x00000000
_STGM_READWRITE = 0x00000002
_VTBL_QI = 0
_VTBL_RELEASE = 2
_VTBL_IPF_LOAD = 5
_VTBL_IPF_SAVE = 6
_VTBL_IPS_GET_VALUE = 5
_VTBL_IPS_SET_VALUE = 6
_VTBL_IPS_COMMIT = 7


def _vtbl_call(obj_addr: int, index: int, restype: type, *argtypes: type):
    vtbl = ctypes.c_void_p.from_address(obj_addr).value
    func_ptr = ctypes.c_void_p.from_address(
        vtbl + index * ctypes.sizeof(ctypes.c_void_p)
    ).value
    return ctypes.WINFUNCTYPE(restype, ctypes.c_void_p, *argtypes)(func_ptr)


def _release(obj_addr: int) -> None:
    _vtbl_call(obj_addr, _VTBL_RELEASE, ctypes.c_ulong)(obj_addr)


def _query_interface(obj_addr: int, iid: _GUID) -> int:
    out = ctypes.c_void_p()
    hr = _vtbl_call(obj_addr, _VTBL_QI, ctypes.HRESULT,
                    ctypes.POINTER(_GUID), ctypes.POINTER(ctypes.c_void_p))(
        obj_addr, ctypes.byref(iid), ctypes.byref(out))
    if hr < 0:
        raise _hresult("QueryInterface", hr)
    return out.value


def set_shortcut_app_user_model_id(lnk_path: str, app_id: str, *, ole32=_ole32) -> None:
    """Write *app_id* into the shortcut at *lnk_path* as its AppUserModelID.

    Only an initialisation that succeeded gets undone.  ``CoInitializeEx``
    answers ``S_OK`` when it opened the apartment and ``S_FALSE`` when the thread
    already had one -- both took a reference this thread owes back -- and a
    failure HRESULT when it took none, which here means ``RPC_E_CHANGED_MODE``:
    something else put this thread in the other concurrency model first.
    Uninitialising anyway would decrement *that* initialisation's count, and the
    apartment its owner is holding objects in can close under them -- while the
    stamping below would be asking for a shell link with no apartment of its own.
    """
    com = ole32()
    hr = com.CoInitializeEx(None, _COINIT_APARTMENTTHREADED)
    if hr < 0:
        raise _hresult("CoInitializeEx", hr)
    try:
        _set_lnk_aumid(lnk_path, app_id, com)
    finally:
        com.CoUninitialize()


def _set_lnk_aumid(lnk_path: str, app_id: str, com) -> None:
    shell_link = ctypes.c_void_p()
    hr = com.CoCreateInstance(
        ctypes.byref(_CLSID_ShellLink), None, _CLSCTX_ALL,
        ctypes.byref(_IID_IShellLinkW), ctypes.byref(shell_link),
    )
    if hr < 0:
        raise _hresult("CoCreateInstance(ShellLink)", hr)
    try:
        persist_file = _query_interface(shell_link.value, _IID_IPersistFile)
        try:
            hr = _vtbl_call(persist_file, _VTBL_IPF_LOAD,
                            ctypes.HRESULT, wintypes.LPCWSTR, ctypes.c_ulong)(
                persist_file, lnk_path, _STGM_READWRITE)
            if hr < 0:
                raise _hresult("IPersistFile::Load", hr)

            prop_store = _query_interface(shell_link.value, _IID_IPropertyStore)
            try:
                pv = _PROPVARIANT()
                pv.vt = _VT_LPWSTR
                pv.pwszVal = app_id

                hr = _vtbl_call(prop_store, _VTBL_IPS_SET_VALUE,
                                ctypes.HRESULT,
                                ctypes.POINTER(_PROPERTYKEY),
                                ctypes.POINTER(_PROPVARIANT))(
                    prop_store,
                    ctypes.byref(_PKEY_AppUserModel_ID),
                    ctypes.byref(pv))
                if hr < 0:
                    raise _hresult("IPropertyStore::SetValue", hr)

                hr = _vtbl_call(prop_store, _VTBL_IPS_COMMIT, ctypes.HRESULT)(prop_store)
                if hr < 0:
                    raise _hresult("IPropertyStore::Commit", hr)
            finally:
                _release(prop_store)

            hr = _vtbl_call(persist_file, _VTBL_IPF_SAVE,
                            ctypes.HRESULT, wintypes.LPCWSTR, wintypes.BOOL)(
                persist_file, lnk_path, True)
            if hr < 0:
                raise _hresult("IPersistFile::Save", hr)
        finally:
            _release(persist_file)
    finally:
        _release(shell_link.value)


def read_shortcut_app_user_model_id(lnk_path: str, *, ole32=_ole32) -> str | None:
    """The AppUserModelID the shortcut at *lnk_path* carries, or ``None`` for none.

    The inverse of :func:`set_shortcut_app_user_model_id`, in the same apartment
    bracket for the same reason.  It exists because a stamp that reported
    success still has to be read back to be believed -- the one failure in this
    module Windows reports no error for is a wrong property key, which writes a
    real value under the wrong name -- so this is what a test of the stamp asks,
    and what a launcher asks of a pin it did not write.
    """
    com = ole32()
    hr = com.CoInitializeEx(None, _COINIT_APARTMENTTHREADED)
    if hr < 0:
        raise _hresult("CoInitializeEx", hr)
    try:
        return _get_lnk_aumid(lnk_path, com)
    finally:
        com.CoUninitialize()


def _get_lnk_aumid(lnk_path: str, com) -> str | None:
    shell_link = ctypes.c_void_p()
    hr = com.CoCreateInstance(
        ctypes.byref(_CLSID_ShellLink), None, _CLSCTX_ALL,
        ctypes.byref(_IID_IShellLinkW), ctypes.byref(shell_link),
    )
    if hr < 0:
        raise _hresult("CoCreateInstance(ShellLink)", hr)
    try:
        persist_file = _query_interface(shell_link.value, _IID_IPersistFile)
        try:
            hr = _vtbl_call(persist_file, _VTBL_IPF_LOAD,
                            ctypes.HRESULT, wintypes.LPCWSTR, ctypes.c_ulong)(
                persist_file, lnk_path, _STGM_READ)
            if hr < 0:
                raise _hresult("IPersistFile::Load", hr)

            prop_store = _query_interface(shell_link.value, _IID_IPropertyStore)
            try:
                pv = _PROPVARIANT()
                hr = _vtbl_call(prop_store, _VTBL_IPS_GET_VALUE,
                                ctypes.HRESULT,
                                ctypes.POINTER(_PROPERTYKEY),
                                ctypes.POINTER(_PROPVARIANT))(
                    prop_store,
                    ctypes.byref(_PKEY_AppUserModel_ID),
                    ctypes.byref(pv))
                if hr < 0:
                    raise _hresult("IPropertyStore::GetValue", hr)
                try:
                    # A shortcut with no such property answers VT_EMPTY, and
                    # S_OK: absence is an answer here, not a failure.
                    return pv.pwszVal if pv.vt == _VT_LPWSTR else None
                finally:
                    # The string in the variant is COM's allocation, not ours.
                    _declare(com, "PropVariantClear", ctypes.HRESULT,
                             ctypes.POINTER(_PROPVARIANT))(ctypes.byref(pv))
            finally:
                _release(prop_store)
        finally:
            _release(persist_file)
    finally:
        _release(shell_link.value)


# --- May I run?  A named mutex, and the handle that answers ------------------

_ERROR_ALREADY_EXISTS = 183
_SYNCHRONIZE = 0x00100000


def mutex_name(base: str, identity: str | Path) -> str:
    """The mutex name for *base* and *identity*.

    *identity* is whatever makes one session different from another -- a config
    path, a profile directory.  The same identity always gives the same name, so
    one identity blocks its own duplicates while a session started on another
    runs beside it untroubled.

    The digest is not a hash of anything secret; it is here because a mutex name
    is a flat namespace shared with every other process on the machine, and a
    path cannot go in one (``\\`` is the namespace separator).  What matters is
    that it never changes: a name spelled differently does not refuse a second
    launch, it lets it through beside the first.
    """
    suffix = hashlib.md5(str(identity).encode()).hexdigest()[:12]
    return f"{base}.{suffix}"


def try_acquire_mutex(name: str, *, kernel32=_kernel32, last_error=_last_error) -> int | None:
    """Claim *name*, and hand back the handle that holds it -- or ``None``.

    **The caller must keep the handle for as long as it means to hold the
    mutex.**  Windows releases a named mutex when the last handle to it closes,
    and a handle nothing refers to is closed by the interpreter at its leisure:
    a guard whose handle was dropped stops guarding some time later, silently,
    and the second instance it exists to refuse then starts.  That is the shape
    of the defect this replaces, which is why the handle is the return value
    rather than a ``bool`` -- a caller can ignore a return, but it has to go out
    of its way to.

    ``None`` means "do not run": either another process holds the mutex, or
    Windows would not make one.  Those are not the same thing, and one of the
    copies this replaces starts anyway on the second -- the caller that cares
    about the difference should ask before it decides.
    """
    dll = kernel32()
    create = _declare(dll, "CreateMutexW", ctypes.c_void_p,
                      ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR)
    close = _declare(dll, "CloseHandle", wintypes.BOOL, ctypes.c_void_p)

    handle = create(None, False, name)
    if not handle:
        return None
    if last_error() == _ERROR_ALREADY_EXISTS:
        # The handle is real and refers to somebody else's mutex. Letting it go
        # is not optional: held to exit, it keeps the mutex alive past the death
        # of the process that owns it.
        close(handle)
        return None
    return handle


def is_mutex_held(name: str, *, kernel32=_kernel32) -> bool:
    """Report whether some process is holding *name*.

    Opens rather than creates, so probing a free name cannot leave a mutex
    behind -- a created-then-closed handle would, for those few microseconds,
    make an instance starting alongside believe another one was already up.
    ``SYNCHRONIZE`` is asked for because it is the least this can ask for and
    still be told whether the name exists.
    """
    dll = kernel32()
    open_mutex = _declare(dll, "OpenMutexW", ctypes.c_void_p,
                          wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR)
    close = _declare(dll, "CloseHandle", wintypes.BOOL, ctypes.c_void_p)

    handle = open_mutex(_SYNCHRONIZE, False, name)
    if not handle:
        return False
    close(handle)
    return True


# --- Putting an error where the user will actually see it -------------------

_MB_OK = 0x0
_MB_ICONERROR = 0x10
_MB_SETFOREGROUND = 0x00010000
_MB_TOPMOST = 0x00040000


def show_error_popup(title: str, message: str, *, user32=_user32) -> None:
    """Put *message* on the screen under *title*, in front of everything.

    For the process that has nowhere else to say it: launched hidden from a
    shortcut, no console to print to, no window of its own yet.  Such a process
    has no claim on the foreground, so a plain message box opens *behind*
    whatever the user is looking at -- and a hidden process that exits having
    shown nothing is indistinguishable from one that crashed.
    ``MB_SETFOREGROUND`` and ``MB_TOPMOST`` are what make the dialog the thing
    the user sees; they are the whole reason to reach for this rather than for
    ``MessageBoxW`` directly.

    Alone in this module it raises nothing.  It is the last thing a dying
    process does, and an exception thrown from the error reporter would replace
    an error nobody has been shown yet with one nobody will see either.

    It is also the name a test suite gags.  One unguarded call blocks on a human
    for as long as the run lasts, so there has to be a name to patch that does
    not resolve a Windows-only dotted path to reach.
    """
    show = _declare(user32(), "MessageBoxW", ctypes.c_int,
                    wintypes.HWND, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.UINT)
    show(None, message, title,
         _MB_OK | _MB_ICONERROR | _MB_SETFOREGROUND | _MB_TOPMOST)

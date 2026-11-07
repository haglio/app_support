from __future__ import annotations

import contextlib
import ctypes
import hashlib
import os
import uuid
from collections.abc import Iterable
from ctypes import wintypes
from dataclasses import dataclass
from pathlib import Path

if os.name == "nt":
    import winreg


def _load(name: str):
    """Open a system DLL with ``use_last_error``, so ``ctypes.get_last_error()`` reads what this call set, not what a runtime or an injected DLL ran next."""
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
    """The code the last call through a ``use_last_error`` handle set; ``ctypes.get_last_error`` exists only on Windows."""
    return ctypes.get_last_error()


def _declare(dll, name: str, restype, *argtypes):
    """Give *dll*'s *name* a prototype: ctypes takes an undeclared return as ``c_int``, which truncates a handle, and converts arguments by their Python type."""
    function = getattr(dll, name)
    function.argtypes = list(argtypes)
    function.restype = restype
    return function


def _close_handle(dll):
    return _declare(dll, "CloseHandle", wintypes.BOOL, ctypes.c_void_p)


def _hresult_refusal_for_the_caller_to_weigh(call: str, hr: int) -> OSError:
    """The failure of *call*, spelled as its HRESULT is written: ``0x{hr:08x}`` on a signed value prints ``0x-7ffefefa``."""
    return OSError(f"{call} failed: HRESULT 0x{hr & 0xFFFFFFFF:08x}")


def set_app_user_model_id(app_id: str, *, shell32=_shell32) -> None:
    """Claim *app_id* as this process's taskbar identity. Windows reads it as a window is created, so it must run before any window exists. Raises ``OSError`` when Windows refuses.

    Unclaimed, Windows groups a process by its executable, which the family's apps share with every other program run on this interpreter: they would wear whichever registered that path first's icon and name.
    """
    set_id = _declare(shell32(), "SetCurrentProcessExplicitAppUserModelID",
                      ctypes.c_long, wintypes.LPCWSTR)
    hr = set_id(app_id)
    if hr < 0:  # Win32's FAILED() macro
        raise _hresult_refusal_for_the_caller_to_weigh("SetCurrentProcessExplicitAppUserModelID", hr)


# The vtable indices are each interface's methods in header order; Windows reports no error for a wrong one.

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


# Win32 shell ``System.AppUserModel.*``. A wrong key writes a real value, answers S_OK, and leaves the duplicate taskbar button.
_APP_USER_MODEL = "9F4C2855-9F79-4B39-A8D0-E1D42DE1D5F3"
_PKEY_AppUserModel_RelaunchCommand = _PROPERTYKEY(_make_guid(_APP_USER_MODEL), 2)
_PKEY_AppUserModel_RelaunchIconResource = _PROPERTYKEY(_make_guid(_APP_USER_MODEL), 3)
_PKEY_AppUserModel_RelaunchDisplayNameResource = _PROPERTYKEY(_make_guid(_APP_USER_MODEL), 4)
_PKEY_AppUserModel_ID = _PROPERTYKEY(_make_guid(_APP_USER_MODEL), 5)

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
_VT_EMPTY = 0
_TEXT_BUFFER = 32768
_VTBL_QI = 0
_VTBL_RELEASE = 2
_VTBL_ISL_GET_PATH = 3
_VTBL_ISL_GET_DESCRIPTION = 6
_VTBL_ISL_SET_DESCRIPTION = 7
_VTBL_ISL_GET_WORKING_DIRECTORY = 8
_VTBL_ISL_SET_WORKING_DIRECTORY = 9
_VTBL_ISL_GET_ARGUMENTS = 10
_VTBL_ISL_SET_ARGUMENTS = 11
_VTBL_ISL_GET_ICON_LOCATION = 16
_VTBL_ISL_SET_ICON_LOCATION = 17
_VTBL_ISL_SET_PATH = 20
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
        raise _hresult_refusal_for_the_caller_to_weigh("QueryInterface", hr)
    return out.value


@contextlib.contextmanager
def _apartment(ole32):
    """The COM apartment a shortcut is written or read in. ``CoInitializeEx`` answers ``S_OK`` or ``S_FALSE`` when it took a reference to give back and ``RPC_E_CHANGED_MODE`` when it took none; uninitializing then would decrement another initialization's count."""
    com = ole32()
    hr = com.CoInitializeEx(None, _COINIT_APARTMENTTHREADED)
    if hr < 0:
        raise _hresult_refusal_for_the_caller_to_weigh("CoInitializeEx", hr)
    try:
        yield com
    finally:
        com.CoUninitialize()


def _create_shell_link(com) -> int:
    shell_link = ctypes.c_void_p()
    hr = com.CoCreateInstance(
        ctypes.byref(_CLSID_ShellLink), None, _CLSCTX_ALL,
        ctypes.byref(_IID_IShellLinkW), ctypes.byref(shell_link),
    )
    if hr < 0:
        raise _hresult_refusal_for_the_caller_to_weigh("CoCreateInstance(ShellLink)", hr)
    return shell_link.value


def _load_shortcut(persist_file: int, lnk_path: str, mode: int) -> None:
    hr = _vtbl_call(persist_file, _VTBL_IPF_LOAD,
                    ctypes.HRESULT, wintypes.LPCWSTR, ctypes.c_ulong)(
        persist_file, lnk_path, mode)
    if hr < 0:
        raise _hresult_refusal_for_the_caller_to_weigh("IPersistFile::Load", hr)


def _save(shell_link: int, lnk_path: str) -> None:
    persist_file = _query_interface(shell_link, _IID_IPersistFile)
    try:
        hr = _vtbl_call(persist_file, _VTBL_IPF_SAVE,
                        ctypes.HRESULT, wintypes.LPCWSTR, wintypes.BOOL)(
            persist_file, lnk_path, True)
        if hr < 0:
            raise _hresult_refusal_for_the_caller_to_weigh("IPersistFile::Save", hr)
    finally:
        _release(persist_file)


def _store_app_id(shell_link: int, app_id: str | None) -> None:
    prop_store = _query_interface(shell_link, _IID_IPropertyStore)
    try:
        _store_values(prop_store, ((_PKEY_AppUserModel_ID, app_id),))
    finally:
        _release(prop_store)


def _store_values(prop_store: int, values: Iterable[tuple[_PROPERTYKEY, str | None]]) -> None:
    set_value = _vtbl_call(prop_store, _VTBL_IPS_SET_VALUE, ctypes.HRESULT,
                           ctypes.POINTER(_PROPERTYKEY), ctypes.POINTER(_PROPVARIANT))
    for key, value in values:
        pv = _PROPVARIANT()
        if value is None:
            pv.vt = _VT_EMPTY
        else:
            pv.vt = _VT_LPWSTR
            pv.pwszVal = value
        hr = set_value(prop_store, ctypes.byref(key), ctypes.byref(pv))
        if hr < 0:
            raise _hresult_refusal_for_the_caller_to_weigh("IPropertyStore::SetValue", hr)
    hr = _vtbl_call(prop_store, _VTBL_IPS_COMMIT, ctypes.HRESULT)(prop_store)
    if hr < 0:
        raise _hresult_refusal_for_the_caller_to_weigh("IPropertyStore::Commit", hr)


def _loaded_shell_link(com, lnk_path: str, mode: int) -> int:
    shell_link = _create_shell_link(com)
    try:
        persist_file = _query_interface(shell_link, _IID_IPersistFile)
        try:
            _load_shortcut(persist_file, lnk_path, mode)
        finally:
            _release(persist_file)
    except BaseException:
        _release(shell_link)
        raise
    return shell_link


def set_shortcut_app_user_model_id(lnk_path: str, app_id: str, *, ole32=_ole32) -> None:
    with _apartment(ole32) as com:
        shell_link = _loaded_shell_link(com, lnk_path, _STGM_READWRITE)
        try:
            _store_app_id(shell_link, app_id)
            _save(shell_link, lnk_path)
        finally:
            _release(shell_link)


@dataclass(frozen=True)
class Shortcut:
    target: str
    arguments: str = ""
    working_directory: str = ""
    icon: str = ""
    icon_index: int = 0
    description: str = ""
    app_id: str | None = None


def write_shortcut(lnk_path: str, shortcut: Shortcut, *, ole32=_ole32) -> None:
    with _apartment(ole32) as com:
        shell_link = _shell_link_to_rewrite(com, lnk_path)
        try:
            text = (wintypes.LPCWSTR,)
            for index, method, kinds, values in (
                (_VTBL_ISL_SET_PATH, "SetPath", text, (shortcut.target,)),
                (_VTBL_ISL_SET_ARGUMENTS, "SetArguments", text, (shortcut.arguments,)),
                (_VTBL_ISL_SET_WORKING_DIRECTORY, "SetWorkingDirectory", text, (shortcut.working_directory,)),
                (_VTBL_ISL_SET_DESCRIPTION, "SetDescription", text, (shortcut.description,)),
                (_VTBL_ISL_SET_ICON_LOCATION, "SetIconLocation", (wintypes.LPCWSTR, ctypes.c_int),
                 (shortcut.icon, shortcut.icon_index)),
            ):
                hr = _vtbl_call(shell_link, index, ctypes.HRESULT, *kinds)(shell_link, *values)
                if hr < 0:
                    raise _hresult_refusal_for_the_caller_to_weigh(f"IShellLinkW::{method}", hr)
            _store_app_id(shell_link, shortcut.app_id)
            _save(shell_link, lnk_path)
        finally:
            _release(shell_link)


def _shell_link_to_rewrite(com, lnk_path: str) -> int:
    if Path(lnk_path).is_file():
        with contextlib.suppress(OSError):
            return _loaded_shell_link(com, lnk_path, _STGM_READWRITE)
    return _create_shell_link(com)


def read_shortcut(lnk_path: str, *, ole32=_ole32) -> Shortcut:
    with _apartment(ole32) as com:
        shell_link = _loaded_shell_link(com, lnk_path, _STGM_READ)
        try:
            icon_index = ctypes.c_int()
            icon = _read_text(shell_link, _VTBL_ISL_GET_ICON_LOCATION, "GetIconLocation",
                              (ctypes.POINTER(ctypes.c_int), ctypes.byref(icon_index)))
            return Shortcut(
                target=_read_text(shell_link, _VTBL_ISL_GET_PATH, "GetPath",
                                  (ctypes.c_void_p, None), (wintypes.DWORD, 0)),
                arguments=_read_text(shell_link, _VTBL_ISL_GET_ARGUMENTS, "GetArguments"),
                working_directory=_read_text(shell_link, _VTBL_ISL_GET_WORKING_DIRECTORY,
                                             "GetWorkingDirectory"),
                icon=icon,
                icon_index=icon_index.value,
                description=_read_text(shell_link, _VTBL_ISL_GET_DESCRIPTION, "GetDescription"),
                app_id=_app_id_of(shell_link, com),
            )
        finally:
            _release(shell_link)


def _read_text(shell_link: int, index: int, method: str, *after_the_buffer) -> str:
    buffer = ctypes.create_unicode_buffer(_TEXT_BUFFER)
    function = _vtbl_call(shell_link, index, ctypes.HRESULT, wintypes.LPWSTR, ctypes.c_int,
                          *(argtype for argtype, _ in after_the_buffer))
    hr = function(shell_link, buffer, _TEXT_BUFFER, *(value for _, value in after_the_buffer))
    if hr < 0:
        raise _hresult_refusal_for_the_caller_to_weigh(f"IShellLinkW::{method}", hr)
    return buffer.value


def _app_id_of(shell_link: int, com) -> str | None:
    prop_store = _query_interface(shell_link, _IID_IPropertyStore)
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
            raise _hresult_refusal_for_the_caller_to_weigh("IPropertyStore::GetValue", hr)
        try:
            return pv.pwszVal if pv.vt == _VT_LPWSTR else None
        finally:
            # The string in the variant is COM's allocation, not ours.
            _declare(com, "PropVariantClear", ctypes.HRESULT,
                     ctypes.POINTER(_PROPVARIANT))(ctypes.byref(pv))
    finally:
        _release(prop_store)


def taskbar_pins() -> Path:
    # Windows' taskbar keeps its own copy of every pinned shortcut here, apart from the shortcut it was pinned from.
    return (Path(os.environ.get("APPDATA", "")) / "Microsoft" / "Internet Explorer"
            / "Quick Launch" / "User Pinned" / "TaskBar")


def stamp_pinned_shortcuts(app_id: str, names: Iterable[str], *, pins: Path | None = None,
                           stamp=set_shortcut_app_user_model_id) -> dict[Path, OSError | None]:
    wanted = {name.lower() for name in names}
    folder = taskbar_pins() if pins is None else pins
    if not folder.is_dir():
        return {}
    results: dict[Path, OSError | None] = {}
    for lnk in sorted(folder.glob("*.lnk")):
        if lnk.stem.lower() not in wanted:
            continue
        try:
            stamp(str(lnk), app_id)
        except OSError as refusal:
            results[lnk] = refusal
        else:
            results[lnk] = None
    return results



@dataclass(frozen=True)
class TaskbarApp:
    name: str
    icon: Path
    relaunch: str


def dress_window(hwnd: int, app_id: str, app: TaskbarApp | None = None, *,
                 shell32=_shell32) -> None:
    """Put *app_id* on *hwnd*, and with *app* what a shortcut would give its taskbar button. Windows reads them as it makes the button, so they go on before the window is first shown, and it uses the name and relaunch command only together; without them the button wears the executable's icon whenever the window is too busy to say its own."""
    get_store = _declare(shell32(), "SHGetPropertyStoreForWindow", ctypes.c_long,
                         wintypes.HWND, ctypes.POINTER(_GUID), ctypes.POINTER(ctypes.c_void_p))
    prop_store = ctypes.c_void_p()
    hr = get_store(hwnd, ctypes.byref(_IID_IPropertyStore), ctypes.byref(prop_store))
    if hr < 0:
        raise _hresult_refusal_for_the_caller_to_weigh("SHGetPropertyStoreForWindow", hr)
    try:
        _store_values(prop_store.value, (
            (_PKEY_AppUserModel_RelaunchCommand, app and app.relaunch),
            (_PKEY_AppUserModel_RelaunchDisplayNameResource, app and app.name),
            (_PKEY_AppUserModel_RelaunchIconResource, app and f"{app.icon},0"),
            (_PKEY_AppUserModel_ID, app_id),
        ))
    finally:
        _release(prop_store.value)


_TASKBAR_APPS = r"Software\Haglio\TaskbarApps"


def _winreg():
    return winreg


def describe_taskbar_app(app_id: str, app: TaskbarApp, *, registry=_winreg) -> None:
    reg = registry()
    with reg.CreateKey(reg.HKEY_CURRENT_USER, rf"{_TASKBAR_APPS}\{app_id}") as key:
        for name, value in (("Name", app.name), ("Icon", str(app.icon)), ("Relaunch", app.relaunch)):
            reg.SetValueEx(key, name, 0, reg.REG_SZ, value)


def described_taskbar_app(app_id: str, *, registry=_winreg) -> TaskbarApp | None:
    reg = registry()
    try:
        with reg.OpenKey(reg.HKEY_CURRENT_USER, rf"{_TASKBAR_APPS}\{app_id}") as key:
            name, icon, relaunch = (reg.QueryValueEx(key, value)[0]
                                    for value in ("Name", "Icon", "Relaunch"))
    except OSError:
        return None
    return TaskbarApp(name=name, icon=Path(icon), relaunch=relaunch)


_ERROR_ALREADY_EXISTS = 183
_SYNCHRONIZE = 0x00100000


def mutex_name(base: str, identity: str | Path) -> str:
    # Win32 object names share one flat namespace and read a backslash as a separator, so the identity goes in as a
    # digest; a name spelled differently refuses nothing and lets a second copy start beside the first.
    suffix = hashlib.md5(str(identity).encode()).hexdigest()[:12]
    return f"{base}.{suffix}"


def try_acquire_mutex(name: str, *, kernel32=_kernel32, last_error=_last_error) -> int | None:
    """Claim *name* and return the handle holding it, or ``None`` for "do not run" (held elsewhere, or Windows would not make one; a caller that must tell the two apart asks ``is_mutex_held`` first). Windows releases a named mutex when its last handle closes, so the caller must keep the handle."""
    dll = kernel32()
    create = _declare(dll, "CreateMutexW", ctypes.c_void_p,
                      ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR)
    close = _close_handle(dll)

    handle = create(None, False, name)
    if not handle:
        return None
    if last_error() == _ERROR_ALREADY_EXISTS:
        # Win32: held to exit, the handle would keep somebody else's mutex alive past its owner's death.
        close(handle)
        return None
    return handle


def release_mutex(handle: int, *, kernel32=_kernel32) -> None:
    _close_handle(kernel32())(handle)


def is_mutex_held(name: str, *, kernel32=_kernel32) -> bool:
    """Win32: opens rather than creates, so probing cannot leave a mutex briefly in place. ``SYNCHRONIZE`` is the least access that still reports whether the name exists."""
    dll = kernel32()
    open_mutex = _declare(dll, "OpenMutexW", ctypes.c_void_p,
                          wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR)
    close = _close_handle(dll)

    handle = open_mutex(_SYNCHRONIZE, False, name)
    if not handle:
        return False
    close(handle)
    return True


_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
_STILL_ACTIVE = 259


def process_started(pid: int, *, kernel32=_kernel32) -> int | None:
    # Windows hands a freed pid out again within seconds, so a pid names a process only beside this start time.
    dll = kernel32()
    open_process = _declare(dll, "OpenProcess", ctypes.c_void_p, wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    exit_code_of = _declare(dll, "GetExitCodeProcess", wintypes.BOOL, ctypes.c_void_p,
                            ctypes.POINTER(wintypes.DWORD))
    times_of = _declare(dll, "GetProcessTimes", wintypes.BOOL, ctypes.c_void_p,
                        *[ctypes.POINTER(wintypes.FILETIME)] * 4)
    close = _close_handle(dll)

    handle = open_process(_PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return None
    try:
        exit_code, created, unread = wintypes.DWORD(), wintypes.FILETIME(), wintypes.FILETIME()
        if not exit_code_of(handle, ctypes.byref(exit_code)) or exit_code.value != _STILL_ACTIVE:
            return None
        if not times_of(handle, ctypes.byref(created), *[ctypes.byref(unread)] * 3):
            return None
        return _ticks(created)
    finally:
        close(handle)


def _ticks(filetime: wintypes.FILETIME) -> int:
    return filetime.dwHighDateTime << 32 | filetime.dwLowDateTime


_ACCOUNTING = 1
_PROCESS_ID_LIST = 3
_EXTENDED_LIMITS = 9
_KILL_ON_JOB_CLOSE = 0x00002000
_BREAKAWAY_OK = 0x00000800
_PRIORITY_CLASS = 0x00000020
_MAXIMUM_WAIT_OBJECTS = 64
_ENDED_WITHIN_MS = 10_000
_TICKS_A_SECOND = 10_000_000


class _Accounting(ctypes.Structure):
    _fields_ = [("user", ctypes.c_longlong), ("kernel", ctypes.c_longlong),
                ("this_period_user", ctypes.c_longlong), ("this_period_kernel", ctypes.c_longlong),
                ("page_faults", wintypes.DWORD), ("processes", wintypes.DWORD),
                ("active_processes", wintypes.DWORD), ("terminated_processes", wintypes.DWORD)]


class _ProcessIdList(ctypes.Structure):
    _fields_ = [("assigned", wintypes.DWORD), ("listed", wintypes.DWORD), ("ids", ctypes.c_size_t * 1024)]


class _BasicLimits(ctypes.Structure):
    _fields_ = [("per_process_user_time", ctypes.c_longlong), ("per_job_user_time", ctypes.c_longlong),
                ("flags", wintypes.DWORD), ("minimum_working_set", ctypes.c_size_t),
                ("maximum_working_set", ctypes.c_size_t), ("active_processes", wintypes.DWORD),
                ("affinity", ctypes.c_size_t), ("priority_class", wintypes.DWORD),
                ("scheduling_class", wintypes.DWORD)]


class _ExtendedLimits(ctypes.Structure):
    _fields_ = [("basic", _BasicLimits), ("io", ctypes.c_ulonglong * 6), ("process_memory", ctypes.c_size_t),
                ("job_memory", ctypes.c_size_t), ("peak_process_memory", ctypes.c_size_t),
                ("peak_job_memory", ctypes.c_size_t)]


def _limits(processes_end_with_it: bool, processes_may_break_away: bool,
            priority_class: int | None) -> _ExtendedLimits:
    limits = _ExtendedLimits()
    limits.basic.flags = ((_KILL_ON_JOB_CLOSE if processes_end_with_it else 0)
                          | (_BREAKAWAY_OK if processes_may_break_away else 0)
                          | (_PRIORITY_CLASS if priority_class is not None else 0))
    limits.basic.priority_class = priority_class or 0
    return limits


class JobObject:
    def __init__(self, process: int | None = None, *, processes_end_with_it: bool = False,
                 processes_may_break_away: bool = False, priority_class: int | None = None,
                 kernel32=_kernel32) -> None:
        dll = kernel32()
        create = _declare(dll, "CreateJobObjectW", ctypes.c_void_p, ctypes.c_void_p, wintypes.LPCWSTR)
        limit = _declare(dll, "SetInformationJobObject", wintypes.BOOL, ctypes.c_void_p, ctypes.c_int,
                         ctypes.c_void_p, wintypes.DWORD)
        self._assign = _declare(dll, "AssignProcessToJobObject", wintypes.BOOL, ctypes.c_void_p, ctypes.c_void_p)
        self._terminate = _declare(dll, "TerminateJobObject", wintypes.BOOL, ctypes.c_void_p, wintypes.UINT)
        self._query = _declare(dll, "QueryInformationJobObject", wintypes.BOOL, ctypes.c_void_p, ctypes.c_int,
                               ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD))
        self._open = _declare(dll, "OpenProcess", ctypes.c_void_p, wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
        self._in_job = _declare(dll, "IsProcessInJob", wintypes.BOOL, ctypes.c_void_p, ctypes.c_void_p,
                                ctypes.POINTER(wintypes.BOOL))
        self._wait = _declare(dll, "WaitForMultipleObjects", wintypes.DWORD, wintypes.DWORD,
                              ctypes.POINTER(ctypes.c_void_p), wintypes.BOOL, wintypes.DWORD)
        self._close = _close_handle(dll)
        self._handle = create(None, None)
        if not self._handle:
            raise self._refused("CreateJobObjectW")
        limits = _limits(processes_end_with_it, processes_may_break_away, priority_class)
        try:
            if limits.basic.flags and not limit(self._handle, _EXTENDED_LIMITS, ctypes.byref(limits),
                                                ctypes.sizeof(limits)):
                raise self._refused("SetInformationJobObject")
            if process is not None:
                self.hold(process)
        except OSError:
            self._close(self._handle)
            raise

    def hold(self, process: int) -> None:
        if not self._assign(self._handle, process):
            raise self._refused("AssignProcessToJobObject")

    def _refused(self, call: str) -> OSError:
        return OSError(f"{call} failed: Win32 error {_last_error()}")

    def end_all(self) -> None:
        ending = self._each_process_in_it()
        try:
            self._terminate(self._handle, 1)
            for start in range(0, len(ending), _MAXIMUM_WAIT_OBJECTS):
                some = ending[start:start + _MAXIMUM_WAIT_OBJECTS]
                self._wait(len(some), (ctypes.c_void_p * len(some))(*some), True, _ENDED_WITHIN_MS)
        finally:
            for process in ending:
                self._close(process)

    def process_ids(self) -> list[int]:
        listed = _ProcessIdList()
        if not self._query(self._handle, _PROCESS_ID_LIST, ctypes.byref(listed), ctypes.sizeof(listed), None):
            raise self._refused("QueryInformationJobObject")
        return listed.ids[:listed.listed]

    def busy_seconds(self) -> float:
        if (busy := _busy_seconds_of(self._query, self._handle)) is None:
            raise self._refused("QueryInformationJobObject")
        return busy

    def _each_process_in_it(self) -> list[int]:
        try:
            listed = self.process_ids()
        except OSError:
            return []
        held = []
        for pid in listed:
            process = self._open(_SYNCHRONIZE | _PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
            if not process:
                continue
            still_in_it = wintypes.BOOL()
            if self._in_job(process, self._handle, ctypes.byref(still_in_it)) and still_in_it.value:
                held.append(process)
            else:
                self._close(process)
        return held

    def __enter__(self) -> JobObject:
        return self

    def __exit__(self, *raised: object) -> None:
        self._close(self._handle)


def a_job_ending_with_this_process(process: int | None = None, *, kernel32=_kernel32) -> JobObject:
    if process is None:
        process = _declare(kernel32(), "GetCurrentProcess", ctypes.c_void_p)()
    return JobObject(process, processes_end_with_it=True, kernel32=kernel32)


def _busy_seconds_of(query, job: int | None) -> float | None:
    spent = _Accounting()
    if not query(job, _ACCOUNTING, ctypes.byref(spent), ctypes.sizeof(spent), None):
        return None
    return (spent.user + spent.kernel) / _TICKS_A_SECOND


def busy_seconds_of_the_job_this_process_runs_in(*, kernel32=_kernel32) -> float:
    dll = kernel32()
    query = _declare(dll, "QueryInformationJobObject", wintypes.BOOL, ctypes.c_void_p, ctypes.c_int,
                     ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD))
    if (busy := _busy_seconds_of(query, None)) is not None:
        return busy
    this_process = _declare(dll, "GetCurrentProcess", ctypes.c_void_p)
    times_of = _declare(dll, "GetProcessTimes", wintypes.BOOL, ctypes.c_void_p,
                        *[ctypes.POINTER(wintypes.FILETIME)] * 4)
    created, ended, kernel, user = (wintypes.FILETIME() for _ in range(4))
    times_of(this_process(), *map(ctypes.byref, (created, ended, kernel, user)))
    return (_ticks(kernel) + _ticks(user)) / _TICKS_A_SECOND


_MB_OK = 0x0
_MB_ICONERROR = 0x10
_MB_SETFOREGROUND = 0x00010000
_MB_TOPMOST = 0x00040000


def show_error_popup(title: str, message: str, *, user32=_user32) -> None:  # the one name a suite patches: ctypes.windll exists only on Windows
    """Put *message* on the screen under *title*, in front of everything. A hidden Windows process has no claim on the foreground, so a plain message dialog opens underneath; ``MB_SETFOREGROUND`` and ``MB_TOPMOST`` prevent that. Raises nothing, being the last thing a dying process does."""
    show = _declare(user32(), "MessageBoxW", ctypes.c_int,
                    wintypes.HWND, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.UINT)
    show(None, message, title,
         _MB_OK | _MB_ICONERROR | _MB_SETFOREGROUND | _MB_TOPMOST)


def window_exists(hwnd: int, *, user32=_user32) -> bool:
    """Whether *hwnd* still names a live window; Windows may give a closed window's number to another."""
    return bool(hwnd) and bool(_declare(user32(), "IsWindow", wintypes.BOOL, wintypes.HWND)(hwnd))


class _LASTINPUTINFO(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.UINT), ("dwTime", wintypes.DWORD)]


_TICKS_WRAP = 2**32


def seconds_since_input(*, user32=_user32, kernel32=_kernel32) -> float:
    info = _LASTINPUTINFO(cbSize=ctypes.sizeof(_LASTINPUTINFO))
    last_input = _declare(user32(), "GetLastInputInfo",
                          wintypes.BOOL, ctypes.POINTER(_LASTINPUTINFO))
    if not last_input(ctypes.pointer(info)):
        raise OSError("GetLastInputInfo failed")
    now = _declare(kernel32(), "GetTickCount", wintypes.DWORD)()
    return ((now - info.dwTime) % _TICKS_WRAP) / 1000


def force_foreground_window(hwnd: int, *, user32=_user32, kernel32=_kernel32) -> bool:
    """Put *hwnd* in front from a process Windows would refuse: ``SetForegroundWindow`` is silently refused unless the process owns the foreground or got the last input, and sharing the foreground thread's input queue is accepted, so the queues are attached for the call. Returns whether the window ended up in front."""
    if not window_exists(hwnd, user32=user32):
        return False
    user = user32()
    foreground_window = _declare(user, "GetForegroundWindow", wintypes.HWND)
    owner_thread = _declare(user, "GetWindowThreadProcessId",
                            wintypes.DWORD, wintypes.HWND, wintypes.LPDWORD)
    foreground = foreground_window() or 0
    this_thread = _declare(kernel32(), "GetCurrentThreadId", wintypes.DWORD)()
    with _input_queue_shared(user, owner_thread(foreground or hwnd, None), this_thread):
        _declare(user, "BringWindowToTop", wintypes.BOOL, wintypes.HWND)(hwnd)
        _declare(user, "SetForegroundWindow", wintypes.BOOL, wintypes.HWND)(hwnd)
        if not foreground:
            _declare(user, "SetActiveWindow", wintypes.HWND, wintypes.HWND)(hwnd)
    return (foreground_window() or 0) == hwnd


@contextlib.contextmanager
def _input_queue_shared(user, other_thread: int, this_thread: int):
    """Win32: *this_thread* reading *other_thread*'s input queue for the block; left joined, the two programs' keyboard focus would move together."""
    attach = _declare(user, "AttachThreadInput",
                      wintypes.BOOL, wintypes.DWORD, wintypes.DWORD, wintypes.BOOL)
    attached = bool(other_thread and other_thread != this_thread
                    and attach(other_thread, this_thread, True))
    try:
        yield
    finally:
        if attached:
            attach(other_thread, this_thread, False)

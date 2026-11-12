"""Copies the venv's interpreter launcher under an app's own image name, version description and icon.

Windows takes the task list's Name, Processes-tab description and icon from the file a process started from.
The copy stays in the venv's ``Scripts`` directory, where Python finds ``pyvenv.cfg``. It is the launcher,
not the base ``python.exe`` it redirects to: a copy of the base interpreter loses the DLL search path Qt needs.
CPython's launcher runs the real interpreter as a child named ``python.exe``, held in a Win32 job object, so ending
the named parent ends that unnamed worker with it.
"""
from __future__ import annotations

import ctypes
import logging
import re
import shutil
import struct
import sys
from ctypes import wintypes
from pathlib import Path

logger = logging.getLogger(__name__)

_RT_ICON = 3
_RT_GROUP_ICON = 14
_RT_VERSION = 16
_DISCARD_EDITS = True
_KEEP_EDITS = False
_LANG_EN_US = 0x0409
_CODEPAGE_UNICODE = 0x04B0
_VS_FFI_SIGNATURE = 0xFEEF04BD
_VS_FFI_STRUCVERSION = 0x00010000
_VS_FFI_FILEFLAGSMASK = 0x3F
_VOS_NT_WINDOWS32 = 0x00040004
_VFT_APP = 0x00000001

STAMP_FIELD = "AppSupportSource"

_ROLE_RE = re.compile(r"^[A-Za-z]+$")

_WORD_BREAK_RE = re.compile(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")


def _squash(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9]", "", text).casefold()


def exe_prefix(app_name: str) -> str:
    squashed = re.sub(r"[^A-Za-z0-9]", "", app_name)
    if not squashed:
        raise ValueError(f"app name has nothing to make a file name from: {app_name!r}")
    return f"{squashed}-"


def _wstr(text: str) -> bytes:
    return text.encode("utf-16-le") + b"\x00\x00"


def _pad4(data: bytes) -> bytes:
    return data + b"\x00" * (-len(data) % 4)


def _node(key: str, value: bytes, *, value_length: int, wtype: int) -> bytes:
    head = _pad4(struct.pack("<HHH", 0, value_length, wtype) + _wstr(key))
    body = head + value
    return struct.pack("<H", len(body)) + body[2:]


def build_version_info(fields: dict[str, str]) -> bytes:
    """Built whole rather than patched into the interpreter's own: Win32's VS_VERSIONINFO holds every length
    relative to its node, so one longer string moves everything after it."""
    strings = b"".join(
        _pad4(_node(key, _wstr(value), value_length=len(value) + 1, wtype=1))
        for key, value in fields.items()
    )
    string_table = _pad4(_node(f"{_LANG_EN_US:04X}{_CODEPAGE_UNICODE:04X}", strings,
                               value_length=0, wtype=1))
    string_file_info = _pad4(_node("StringFileInfo", string_table, value_length=0, wtype=1))
    translation = _node("Translation", struct.pack("<HH", _LANG_EN_US, _CODEPAGE_UNICODE),
                        value_length=4, wtype=0)
    var_file_info = _pad4(_node("VarFileInfo", _pad4(translation), value_length=0, wtype=1))

    # Win32's VS_FIXEDFILEINFO, in field order from dwSignature to dwFileDateLS.
    fixed = struct.pack(
        "<LLLLLLLLLLLLL",
        _VS_FFI_SIGNATURE,
        _VS_FFI_STRUCVERSION,
        0, 0,
        0, 0,
        _VS_FFI_FILEFLAGSMASK,
        0,
        _VOS_NT_WINDOWS32,
        _VFT_APP,
        0,
        0, 0,
    )
    return _node("VS_VERSION_INFO", fixed + string_file_info + var_file_info,
                 value_length=len(fixed), wtype=0)


def build_icon_resources(ico: bytes) -> tuple[list[bytes], bytes]:
    reserved, kind, count = struct.unpack_from("<HHH", ico, 0)
    if reserved != 0 or kind != 1 or not count:
        raise ValueError("not an icon file")
    images: list[bytes] = []
    entries: list[bytes] = []
    for index in range(count):
        width, height, colors, pad, planes, bits, size, offset = struct.unpack_from(
            "<BBBBHHLL", ico, 6 + index * 16)
        images.append(ico[offset:offset + size])
        entries.append(struct.pack("<BBBBHHLH", width, height, colors, pad,
                                   planes, bits, size, index + 1))
    return images, struct.pack("<HHH", 0, 1, count) + b"".join(entries)


def _kernel32():
    dll = ctypes.WinDLL("kernel32", use_last_error=True)
    dll.BeginUpdateResourceW.restype = wintypes.HANDLE
    dll.BeginUpdateResourceW.argtypes = [wintypes.LPCWSTR, wintypes.BOOL]
    dll.UpdateResourceW.argtypes = [wintypes.HANDLE, wintypes.LPCWSTR, wintypes.LPCWSTR,
                                    wintypes.WORD, wintypes.LPVOID, wintypes.DWORD]
    dll.EndUpdateResourceW.argtypes = [wintypes.HANDLE, wintypes.BOOL]
    return dll


def stamp_identity(exe: Path, *, fields: dict[str, str], icon: bytes | None) -> None:
    version = build_version_info(fields)
    dll = _kernel32()
    handle = dll.BeginUpdateResourceW(str(exe), False)
    if not handle:
        raise OSError(f"BeginUpdateResource failed ({ctypes.get_last_error()})")
    try:
        def put(kind: int, name: int, data: bytes) -> None:
            buf = ctypes.create_string_buffer(data, len(data))
            ok = dll.UpdateResourceW(handle, ctypes.cast(kind, wintypes.LPCWSTR),
                                     ctypes.cast(name, wintypes.LPCWSTR),
                                     _LANG_EN_US, buf, len(data))
            if not ok:
                raise OSError(f"UpdateResource failed ({ctypes.get_last_error()})")

        put(_RT_VERSION, 1, version)
        if icon is not None:
            images, directory = build_icon_resources(icon)
            for index, image in enumerate(images):
                put(_RT_ICON, index + 1, image)
            put(_RT_GROUP_ICON, 1, directory)
            # Win32 UpdateResource succeeds when deleting a resource id that is absent, then EndUpdateResource
            # fails with ERROR_INTERNAL_ERROR; the icon images past ours stay in the file for that reason.
    except Exception:
        dll.EndUpdateResourceW(handle, _DISCARD_EDITS)
        raise
    if not dll.EndUpdateResourceW(handle, _KEEP_EDITS):
        raise OSError(f"EndUpdateResource failed ({ctypes.get_last_error()})")


def read_version_field(exe: Path, field: str) -> str | None:
    version_dll = ctypes.WinDLL("version", use_last_error=True)
    version_dll.GetFileVersionInfoSizeW.argtypes = [wintypes.LPCWSTR, wintypes.LPDWORD]
    version_dll.GetFileVersionInfoW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD,
                                                wintypes.DWORD, wintypes.LPVOID]
    version_dll.VerQueryValueW.argtypes = [wintypes.LPCVOID, wintypes.LPCWSTR,
                                           ctypes.POINTER(wintypes.LPVOID),
                                           ctypes.POINTER(wintypes.UINT)]
    size = version_dll.GetFileVersionInfoSizeW(str(exe), None)
    if not size:
        return None
    block = ctypes.create_string_buffer(size)
    if not version_dll.GetFileVersionInfoW(str(exe), 0, size, block):
        return None
    value = wintypes.LPVOID()
    length = wintypes.UINT()
    query = f"\\StringFileInfo\\{_LANG_EN_US:04X}{_CODEPAGE_UNICODE:04X}\\{field}"
    if not version_dll.VerQueryValueW(block, query, ctypes.byref(value), ctypes.byref(length)):
        return None
    if not length.value:
        return None
    return ctypes.wstring_at(value.value, length.value - 1)


def _launcher_beside_the_running_copy(interpreter: str) -> Path:
    return Path(sys.executable).with_name(interpreter)


class ProcessNamer:
    def __init__(self, app_name: str, icon: str | Path | None = None, *,
                 stamp=stamp_identity, read_field=read_version_field) -> None:
        self.app_name = app_name
        self.prefix = exe_prefix(app_name)
        self.icon = Path(icon) if icon is not None else None
        self._stamp = stamp
        self._read_field = read_field

    def exe_name(self, python_exe: str | Path, role: str) -> str:
        if not _ROLE_RE.match(role):
            raise ValueError(f"role must be plain letters, got {role!r}")
        return f"{self.prefix}{role}{Path(python_exe).suffix}"  # the prefix leads, so Windows' task list sorts an app's rows together

    def description(self, role: str) -> str:
        if _squash(role) == _squash(self.app_name):
            return self.app_name
        return f"{self.app_name} \u2013 {_WORD_BREAK_RE.sub(' ', role)}"

    @property
    def _copy_name_pattern(self) -> str:
        return "^" + self.prefix + r"[A-Za-z]+\.exe$"

    @property
    def process_name_pattern(self) -> str:
        # Read by PowerShell's -match, in the apps' process sweeps.
        return r"^pythonw?\.exe$|^py\.exe$|" + self._copy_name_pattern

    def owns_exe_name(self, name: str) -> bool:
        return re.fullmatch(self._copy_name_pattern, name, re.IGNORECASE) is not None

    def named_exe(self, python_exe: str | Path, role: str) -> str:
        source = Path(python_exe)
        try:
            target = source.with_name(self.exe_name(source, role))
            description = self.description(role)
            stamp = self._source_stamp(source, description)
        except Exception:
            logger.warning("Not naming the %s process", role, exc_info=True)
            return str(python_exe)

        if self._is_current(target, stamp):
            return str(target)

        try:
            icon = self.icon.read_bytes() if self.icon and self.icon.is_file() else None
        except OSError:
            icon = None

        try:
            # CPython's shutil.copy2 treats a directory destination as "copy into"; copyfile refuses it.
            shutil.copyfile(source, target)
            self._stamp(target, icon=icon, fields={
                "CompanyName": self.app_name,
                "FileDescription": description,
                "InternalName": target.stem,
                "OriginalFilename": target.name,
                "ProductName": self.app_name,
                STAMP_FIELD: stamp,
            })
        except Exception:
            if self._is_ours(target):
                logger.info("Kept the existing %s launcher; could not refresh it", target.name)
                return str(target)
            self._discard(target)
            logger.warning("Not naming the %s process; launching unnamed", role, exc_info=True)
            return str(python_exe)
        return str(target)

    def name_this_process(self, role: str, interpreter: str = "pythonw.exe") -> None:
        try:
            self.named_exe(_launcher_beside_the_running_copy(interpreter), role)
        except Exception:
            logger.warning("Not naming this process (%s); launching unnamed", role, exc_info=True)

    def _source_stamp(self, source: Path, description: str) -> str:
        stat = source.stat()
        return f"{stat.st_size}:{int(stat.st_mtime)}:{description}"

    def _is_current(self, copy: Path, stamp: str) -> bool:
        if not copy.is_file():
            return False
        try:
            return self._read_field(copy, STAMP_FIELD) == stamp
        except OSError:
            return False

    def _is_ours(self, exe: Path) -> bool:
        if not exe.is_file():
            return False
        try:
            return self._read_field(exe, STAMP_FIELD) is not None
        except OSError:
            return False

    @staticmethod
    def _discard(target: Path) -> None:
        try:
            if target.is_file():
                target.unlink()
        except OSError:
            logger.info("Left %s in place; it could not be removed", target.name, exc_info=True)

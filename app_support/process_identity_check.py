from __future__ import annotations

import ctypes
import shutil
import struct
import sys
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from ctypes import wintypes
from dataclasses import dataclass
from pathlib import Path

from app_support.process_identity import (
    STAMP_FIELD,
    ProcessNamer,
    build_icon_resources,
    read_version_field,
)

# PE IMAGE_SUBSYSTEM_WINDOWS_GUI and _CUI.
_WINDOWED, _CONSOLE = 2, 3
_RT_ICON = 3
_LOAD_LIBRARY_AS_DATAFILE = 0x00000002


def _a_venv_with_the_real_launchers(where: Path) -> Path:
    scripts = where / ".venv" / "Scripts"
    scripts.mkdir(parents=True)
    running = Path(sys.executable)
    for name in ("python.exe", "pythonw.exe"):
        shutil.copyfile(running.with_name(name), scripts / name)
    return scripts


@contextmanager
def _running_under(executable: str) -> Iterator[None]:
    was = sys.executable
    sys.executable = executable
    try:
        yield
    finally:
        sys.executable = was


def _subsystem(exe: Path) -> int:
    with exe.open("rb") as image:
        (pe_offset,) = struct.unpack_from("<I", image.read(0x40), 0x3C)
        image.seek(pe_offset)
        if image.read(4) != b"PE\0\0":
            raise ValueError(f"{exe} is not a PE image")
        # PE: past the 20-byte COFF header, the subsystem sits 68 bytes into the
        # optional header, the same offset for a 32-bit and a 64-bit image.
        image.seek(pe_offset + 4 + 20 + 68)
        (subsystem,) = struct.unpack("<H", image.read(2))
    return subsystem


def _resource(exe: Path, kind: int, name: int) -> bytes | None:
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.LoadLibraryExW.restype = wintypes.HMODULE
    k32.LoadLibraryExW.argtypes = [wintypes.LPCWSTR, wintypes.HANDLE, wintypes.DWORD]
    k32.FindResourceW.restype = wintypes.HANDLE
    k32.FindResourceW.argtypes = [wintypes.HMODULE, ctypes.c_void_p, ctypes.c_void_p]
    k32.SizeofResource.restype = wintypes.DWORD
    k32.SizeofResource.argtypes = [wintypes.HMODULE, wintypes.HANDLE]
    k32.LoadResource.restype = wintypes.HANDLE
    k32.LoadResource.argtypes = [wintypes.HMODULE, wintypes.HANDLE]
    k32.LockResource.restype = ctypes.c_void_p
    k32.LockResource.argtypes = [wintypes.HANDLE]
    k32.FreeLibrary.argtypes = [wintypes.HMODULE]
    module = k32.LoadLibraryExW(str(exe), None, _LOAD_LIBRARY_AS_DATAFILE)
    if not module:
        raise OSError(f"could not open {exe} as data ({ctypes.get_last_error()})")
    try:
        found = k32.FindResourceW(module, ctypes.c_void_p(name), ctypes.c_void_p(kind))
        if not found:
            return None
        size = k32.SizeofResource(module, found)
        return ctypes.string_at(k32.LockResource(k32.LoadResource(module, found)), size)
    finally:
        k32.FreeLibrary(module)


@dataclass(frozen=True)
class ProcessName:
    app_name: str
    role: str
    interpreter: str = "pythonw.exe"
    row: str | None = None
    icon: Path | None = None


def assert_the_process_is_named(name_this_process: Callable[[], object], where: Path, named: ProcessName) -> None:
    app_name, role, interpreter, row, icon = named.app_name, named.role, named.interpreter, named.row, named.icon
    namer = ProcessNamer(app_name)
    scripts = _a_venv_with_the_real_launchers(where)
    before = set(scripts.iterdir())
    the_other_launcher_so_an_app_copying_whatever_it_runs_under_is_caught = (
        "python.exe" if interpreter == "pythonw.exe" else "pythonw.exe")
    with _running_under(str(scripts / the_other_launcher_so_an_app_copying_whatever_it_runs_under_is_caught)):
        name_this_process()
    made = sorted(set(scripts.iterdir()) - before)
    expected = scripts / namer.exe_name(interpreter, role)
    assert made == [expected], (
        f"expected {expected.name} and nothing else beside the interpreter; "
        f"found {[path.name for path in made]}")
    wanted_row = namer.description(role) if row is None else row
    assert read_version_field(expected, "FileDescription") == wanted_row, (
        f"the row would read {read_version_field(expected, 'FileDescription')!r}, "
        f"not {wanted_row!r}")
    assert read_version_field(expected, STAMP_FIELD), (
        "the copy carries no stamp, so no later run will know it is current")
    wanted = _CONSOLE if interpreter == "python.exe" else _WINDOWED
    assert _subsystem(expected) == wanted, (
        f"the copy was not made from {interpreter}: it is "
        f"{'a console' if _subsystem(expected) == _CONSOLE else 'a windowed'} image, one the launcher never starts")
    if icon is not None:
        images, _directory = build_icon_resources(Path(icon).read_bytes())
        assert _resource(expected, _RT_ICON, 1) == images[0], (
            f"the copy does not carry {Path(icon).name}")

    # CPython documents sys.executable as empty then.
    with _running_under(""):
        try:
            name_this_process()
        except Exception as failure:
            raise AssertionError(
                f"with nothing to copy from, the naming raised {failure!r}; "
                "at the top of main() that would take the launch down") from failure

"""That an app names its own process -- run against a throwaway venv, not read off its source.

Every app in the family starts through a copy of its interpreter that says the
app's name (:mod:`app_support.process_identity`), and its own process is the one
it cannot name on the way in -- so each run makes the copy for the run after, and
the launcher starts through it once it is there.  Six suites asserted that half by
reading the entry point as text and looking for the lines: the call, the app name,
the role, the ``with_name("python.exe")``, the ``except Exception:``.  A rename or
a line wrap turned those red with the behavior unchanged, and the call moving into
a branch that never runs left them green with the behavior gone.

So this runs the app's own naming instead.  Hand it the function the entry point
calls and a directory to work in; it stands up a venv's ``Scripts`` directory there
with the real launchers copied in, points ``sys.executable`` into it, calls the
function, and reads what appeared: one copy, named for the app and the role,
described as the row should read, a console image when the launcher runs the
console interpreter, carrying the app's own icon.  Then it calls the function once
more where Python could not say what it is running under, and checks it came back
-- the name is lost there, and nothing else may be::

    from app_support.process_identity_check import assert_the_app_names_its_process

    def test_the_app_prepares_the_copy_its_launcher_starts_through(tmp_path):
        assert_the_app_names_its_process(
            _name_this_process, tmp_path, app_name="Highdeas", role="Highdeas",
            interpreter="python.exe", row="Highdeas", icon=PROJECT_DIR / "icon.ico")

The launcher's side -- that the ``.vbs`` looks for that copy, ahead of the plain
interpreter -- stays a text assertion in each repo: a ``.vbs`` really is a text
file and really does contain the literal.

Windows only, like the naming itself: the copy is described with UpdateResource
and read back with VerQueryValue.  Standard library only, and no pytest: plain
functions raising ``AssertionError``.
"""
from __future__ import annotations

import ctypes
import shutil
import struct
import sys
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from ctypes import wintypes
from pathlib import Path

from app_support.process_identity import (
    STAMP_FIELD,
    ProcessNamer,
    build_icon_resources,
    read_version_field,
)

# IMAGE_SUBSYSTEM_WINDOWS_GUI and _CUI: what a copy inherits from the launcher it
# was made from, and the one thing the file name cannot tell.
_WINDOWED, _CONSOLE = 2, 3
_RT_ICON = 3
_LOAD_LIBRARY_AS_DATAFILE = 0x00000002


def _a_venv_with_the_real_launchers(where: Path) -> Path:
    """A ``Scripts`` directory under *where* holding copies of the two launchers
    beside the running interpreter, ``python.exe`` and ``pythonw.exe``.

    Copies of the real ones rather than stubs: the copy the app makes is
    described by rewriting its version resource, which only a real image can
    carry, so a stub would make every naming fall back and prove nothing.
    """
    scripts = where / ".venv" / "Scripts"
    scripts.mkdir(parents=True)
    running = Path(sys.executable)
    for name in ("python.exe", "pythonw.exe"):
        shutil.copyfile(running.with_name(name), scripts / name)
    return scripts


@contextmanager
def _running_under(executable: str) -> Iterator[None]:
    """``sys.executable`` set to *executable* for the duration."""
    was = sys.executable
    sys.executable = executable
    try:
        yield
    finally:
        sys.executable = was


def _subsystem(exe: Path) -> int:
    """The subsystem *exe* is linked for: console or windowed."""
    with exe.open("rb") as image:
        (pe_offset,) = struct.unpack_from("<I", image.read(0x40), 0x3C)
        image.seek(pe_offset)
        if image.read(4) != b"PE\0\0":
            raise ValueError(f"{exe} is not a PE image")
        # Past the 20-byte COFF header, the subsystem sits 68 bytes into the
        # optional header -- the same offset for a 32-bit and a 64-bit image.
        image.seek(pe_offset + 4 + 20 + 68)
        (subsystem,) = struct.unpack("<H", image.read(2))
    return subsystem


def _resource(exe: Path, kind: int, name: int) -> bytes | None:
    """The bytes of one resource in *exe*, or None if it carries none by that id."""
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


def assert_the_app_names_its_process(
    name_this_process: Callable[[], object], where: Path, *, app_name: str, role: str,
    interpreter: str = "pythonw.exe", row: str | None = None, icon: Path | None = None,
) -> None:
    """*name_this_process*, the call at the top of the app's ``main()``, run
    against a venv stood up under *where*, leaves exactly the copy the app's
    launcher starts it through -- and survives having nothing to copy.

    *interpreter* is the launcher the app's ``.vbs`` or shortcut runs:
    ``python.exe`` when it redirects the app's output into a log, ``pythonw.exe``
    for a shortcut.  The copy has to have been made from that one -- a windowed
    copy for a console launcher is a copy nothing ever starts -- and it is told
    apart by the subsystem the copy inherits, the one thing its name cannot say.
    The run is pointed at the OTHER launcher on purpose: an app that copies
    whatever it happens to be running under names a copy after a copy on every
    run after the first, and here it also makes the wrong kind of image.

    *row* is what the Processes tab should show -- the app's name alone, for an
    app with one window -- and *icon* the mark the copy should carry, if the app
    has one.
    """
    namer = ProcessNamer(app_name)
    scripts = _a_venv_with_the_real_launchers(where)
    before = set(scripts.iterdir())
    other = "python.exe" if interpreter == "pythonw.exe" else "pythonw.exe"
    with _running_under(str(scripts / other)):
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
        f"{'a console' if _subsystem(expected) == _CONSOLE else 'a windowed'} image")
    if icon is not None:
        images, _directory = build_icon_resources(Path(icon).read_bytes())
        assert _resource(expected, _RT_ICON, 1) == images[0], (
            f"the copy does not carry {Path(icon).name}")

    # Python could not say what it is running under -- sys.executable is
    # documented to be empty then -- so there is nothing to copy from.  That
    # costs the name and nothing else: the call comes back.
    with _running_under(""):
        try:
            name_this_process()
        except Exception as failure:
            raise AssertionError(
                f"with nothing to copy from, the naming raised {failure!r}; "
                "at the top of main() that would take the launch down") from failure

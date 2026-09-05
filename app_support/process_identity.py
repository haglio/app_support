"""Make an app's processes say what they are in the Windows task list.

Every app here runs as ``pythonw.exe``, so the task list shows a column of
identical "Python" rows.  That is not a cosmetic problem.  When something
strands a process -- a launcher that dies without reaping, a window that closed
without its worker -- the task list is the only way back, and it cannot say
which rows are safe to end.  A user looking at six anonymous Pythons, three of
them somebody else's, is being asked to guess.

Windows decides what it shows about a process from the *file it was started
from*, and from three fields of that file:

  * the **image name**, which is the Details tab's Name column;
  * the **file description** in the version resource, which is what the
    Processes tab actually displays -- and the reason renaming the file alone
    still leaves a list reading "Python" all the way down;
  * the **icon**, likewise from the file rather than from any window.

So an app that wants to be identifiable starts through a copy of its own
interpreter, with all three rewritten: ``Highdeas-Highdeas.exe`` described as
"Highdeas", carrying Highdeas's mark.  :class:`ProcessNamer` makes those copies.

Two details of *which* interpreter is copied *where* are load-bearing, and both
were settled by trying the alternative:

  * The copy stays in the venv's ``Scripts`` directory.  Python finds
    ``pyvenv.cfg`` one level up from there, so the copy is the same venv with
    the same ``site-packages``.
  * What gets copied is that directory's launcher, NOT the base interpreter it
    redirects to.  Dropping a copy of the base ``python.exe`` into ``Scripts``
    also resolves the venv, and it has the appeal of running as a single
    process -- but it loses the DLL search path PyQt6 needs and dies on
    ``import QtGui``, which is every Qt window these apps own.

Copying the launcher means the real interpreter still runs as a child named
``python.exe``, so a named parent has an anonymous worker under it.  That is the
cost of the approach, and it is worth paying: the launcher holds its child in a
job object, so ending the named parent takes the worker with it -- which is the
whole point of being able to find the named parent.

Naming a process is never worth failing a launch over, so every failure here
falls back to the interpreter it was handed and the app starts exactly as it did
before.
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
_LANG_EN_US = 0x0409
_CODEPAGE_UNICODE = 0x04B0

# Which source a copy was made from and what it was labelled, recorded in the
# copy's own version resource.  Size and mtime cannot answer it -- rewriting the
# resource changes both -- and this says more than they did: it goes stale when
# the interpreter is upgraded AND when the label the app would write changes.
STAMP_FIELD = "AppSupportSource"

_ROLE_RE = re.compile(r"^[A-Za-z]+$")

# Where a CamelCase role breaks into words.  A capital starts a word only when
# the character before it was lower-case, or when it heads a capitalised word
# after a run of capitals -- so an acronym stays whole.  Breaking at every
# capital turned "GenauVR" into "Genau V R", which then no longer matched the
# app's own name and got that name pasted in front of it as well.
_WORD_BREAK_RE = re.compile(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")


def _squash(text: str) -> str:
    """*text* with everything but letters and digits taken out, folded for case."""
    return re.sub(r"[^A-Za-z0-9]", "", text).casefold()


def exe_prefix(app_name: str) -> str:
    """The file-name prefix every copy for *app_name* carries.

    Spaces and punctuation come out because this becomes a file name.  The
    prefix is what makes an app's processes gather together in a task list
    sorted by name, and what lets a process sweep bound itself to one app
    without knowing which roles that app has.
    """
    squashed = re.sub(r"[^A-Za-z0-9]", "", app_name)
    if not squashed:
        raise ValueError(f"app name has nothing to make a file name from: {app_name!r}")
    return f"{squashed}-"


# --- Building the resources -------------------------------------------------

def _wstr(text: str) -> bytes:
    return text.encode("utf-16-le") + b"\x00\x00"


def _pad4(data: bytes) -> bytes:
    return data + b"\x00" * (-len(data) % 4)


def _node(key: str, value: bytes, *, value_length: int, wtype: int) -> bytes:
    """One node of a version resource: header, key, then the aligned value.

    ``wLength`` counts the header, the key and the value together with the
    padding that aligns the value -- but not any padding that follows it, which
    belongs to the next sibling instead.
    """
    head = _pad4(struct.pack("<HHH", 0, value_length, wtype) + _wstr(key))
    body = head + value
    return struct.pack("<H", len(body)) + body[2:]


def build_version_info(fields: dict[str, str]) -> bytes:
    """A whole VS_VERSIONINFO carrying *fields*.

    Built rather than patched: the strings an app wants are longer than the ones
    Python ships, and every length and offset in the format is relative, so
    editing one string in place means rewriting the structure around it anyway.
    """
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

    fixed = struct.pack(
        "<LLLLLLLLLLLLL",
        0xFEEF04BD,   # dwSignature
        0x00010000,   # dwStrucVersion
        0, 0,         # dwFileVersion MS / LS
        0, 0,         # dwProductVersion MS / LS
        0x3F,         # dwFileFlagsMask
        0,            # dwFileFlags
        0x00040004,   # dwFileOS = VOS_NT_WINDOWS32
        0x00000001,   # dwFileType = VFT_APP
        0,            # dwFileSubtype
        0, 0,         # dwFileDate MS / LS
    )
    return _node("VS_VERSION_INFO", fixed + string_file_info + var_file_info,
                 value_length=len(fixed), wtype=0)


def build_icon_resources(ico: bytes) -> tuple[list[bytes], bytes]:
    """Split a .ico into its images and a directory that indexes them by id.

    An .ico on disk and an icon in a PE are the same images behind two different
    directories: the file's points at byte offsets, the resource's at resource
    ids.  So the images go in untouched and only the directory is rebuilt.
    """
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


# --- Writing them into the copy ---------------------------------------------

def _kernel32():
    dll = ctypes.WinDLL("kernel32", use_last_error=True)
    dll.BeginUpdateResourceW.restype = wintypes.HANDLE
    dll.BeginUpdateResourceW.argtypes = [wintypes.LPCWSTR, wintypes.BOOL]
    dll.UpdateResourceW.argtypes = [wintypes.HANDLE, wintypes.LPCWSTR, wintypes.LPCWSTR,
                                    wintypes.WORD, wintypes.LPVOID, wintypes.DWORD]
    dll.EndUpdateResourceW.argtypes = [wintypes.HANDLE, wintypes.BOOL]
    return dll


def stamp_identity(exe: Path, *, fields: dict[str, str], icon: bytes | None) -> None:
    """Write *fields* and *icon* into *exe*'s resources.

    One update handle for all of it, so a failure part-way leaves the file
    untouched rather than half relabelled: ``EndUpdateResource`` is what rewrites
    it, once, at the end.

    The interpreter's own application manifest is deliberately left alone -- it
    carries the DPI awareness every window the app opens inherits, so losing it
    would rescale the app to make a task list readable.
    """
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
            # Python ships more icon images than an app's mark usually has, and
            # the ones past ours stay in the file as orphans.  They are left
            # there on purpose: nothing references them once the group above is
            # rewritten, and sweeping them out is not free.  Deleting a resource
            # id that is not there returns success from UpdateResource and then
            # fails the whole EndUpdateResource with ERROR_INTERNAL_ERROR -- so a
            # tidying pass over a fixed id range threw away the relabelling it
            # came with.
    except Exception:
        dll.EndUpdateResourceW(handle, True)  # discard
        raise
    if not dll.EndUpdateResourceW(handle, False):
        raise OSError(f"EndUpdateResource failed ({ctypes.get_last_error()})")


def read_version_field(exe: Path, field: str) -> str | None:
    """Read one string out of *exe*'s version resource, or None if it has none."""
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


class ProcessNamer:
    """Makes the named interpreters one app's processes are started through.

    *app_name* is what the task list should read -- "Fun Time", "Highdeas" --
    and *icon* is the .ico to stamp beside it, if the app has one.

    An app with one window names it after itself and gets a row reading just the
    app name; an app that launches several says which is which
    (``Fun Time – Audio Companion``).
    """

    def __init__(self, app_name: str, icon: str | Path | None = None, *,
                 stamp=stamp_identity, read_field=read_version_field) -> None:
        # *stamp* and *read_field* are the two calls that need a real PE and a
        # real Win32; injectable so the keep/refresh/discard decisions are
        # testable on any platform, with the defaults every consumer gets.
        self.app_name = app_name
        self.prefix = exe_prefix(app_name)
        self.icon = Path(icon) if icon is not None else None
        self._stamp = stamp
        self._read_field = read_field

    # --- what things are called ---

    def exe_name(self, python_exe: str | Path, role: str) -> str:
        """The file name a *role*'s copy of *python_exe* gets.

        The suffix comes from the interpreter rather than being hardcoded, so a
        console child copied from ``python.exe`` and a windowed one copied from
        ``pythonw.exe`` both keep the console behavior they were launched for --
        naming a process must not decide whether it has a console.
        """
        if not _ROLE_RE.match(role):
            raise ValueError(f"role must be plain letters, got {role!r}")
        return f"{self.prefix}{role}{Path(python_exe).suffix}"

    def description(self, role: str) -> str:
        """What the Processes tab shows for *role*.

        The role is a single CamelCase word because it also has to be a file
        name; split back apart here so the row reads as English rather than as
        an identifier.  A role that just repeats the app's own name -- the usual
        case for an app with one window -- leaves the app name standing alone
        rather than saying it twice.
        """
        # Compared with the spacing taken out of both, because the role had to
        # be one word to be a file name while the app name did not: comparing
        # the SPLIT role against the app name said PromptCrafter's own role was
        # a different thing from PromptCrafter, and the row read "PromptCrafter
        # - Prompt Crafter".
        if _squash(role) == _squash(self.app_name):
            return self.app_name
        return f"{self.app_name} – {_WORD_BREAK_RE.sub(' ', role)}"

    @property
    def _copy_name_pattern(self) -> str:
        """A regex matching the image names this namer's own copies carry.

        The prefix goes in as it stands: exe_prefix leaves only letters, digits
        and the hyphen it appends, none of which a regex reads.  Escaping it
        spelled the prefix one way here and another on disk, in a string whose
        readers compare the two by eye.
        """
        return "^" + self.prefix + r"[A-Za-z]+\.exe$"

    @property
    def process_name_pattern(self) -> str:
        """A regex matching every image name one of this app's processes can run
        under: a role-named copy, or -- when the copy could not be made -- the
        plain interpreter it falls back to.

        Written for PowerShell's ``-match``, which is where process sweeps apply
        it, and anchored so it cannot catch some other app's ``mypythonw.exe``.
        """
        return r"^pythonw?\.exe$|^py\.exe$|" + self._copy_name_pattern

    def owns_exe_name(self, name: str) -> bool:
        """Whether *name* is one of the role-named copies this namer makes.

        Narrower than :attr:`process_name_pattern`, and built from the same rule
        so the two cannot come to disagree: this asks whether the app NAMED the
        process, where the pattern asks whether the process could be the app's
        at all.  A caller bounded by nothing but the image name wants this one
        -- the plain interpreters the pattern also matches are as likely to be
        somebody else's.
        """
        return re.fullmatch(self._copy_name_pattern, name, re.IGNORECASE) is not None

    # --- making them ---

    def named_exe(self, python_exe: str | Path, role: str) -> str:
        """Return an interpreter that runs *role* under a name naming this app.

        Makes the described, role-named copy beside *python_exe* if it is
        missing or stale, and returns it.  Returns *python_exe* unchanged if the
        copy cannot be made -- a read-only venv, an antivirus hold, a disk that
        is full.  The app then runs exactly as it did before, with an anonymous
        process: a worse task list and a working app.
        """
        source = Path(python_exe)
        try:
            target = source.with_name(self.exe_name(source, role))
            description = self.description(role)
            stamp = self._source_stamp(source, description)
        except (ValueError, OSError):
            logger.warning("Not naming the %s process", role, exc_info=True)
            return str(python_exe)

        if self._is_current(target, stamp):
            return str(target)

        try:
            icon = self.icon.read_bytes() if self.icon and self.icon.is_file() else None
        except OSError:
            icon = None

        try:
            # copyfile rather than copy2, which treats a directory destination
            # as "copy INTO this" -- so something of our name that is not a file
            # (a directory left by a botched cleanup) made the copy report
            # success and handed the launcher a directory to run.  copyfile
            # refuses it instead.
            shutil.copyfile(source, target)
            self._stamp(target, icon=icon, fields={
                "CompanyName": self.app_name,
                "FileDescription": description,
                "InternalName": target.stem,
                "OriginalFilename": target.name,
                "ProductName": self.app_name,
                STAMP_FIELD: stamp,
            })
        except (OSError, ValueError):
            # A described copy already there, one label or one Python upgrade
            # behind, still names its process -- better than going back to an
            # anonymous one.  That is the usual way to land here: the last run's
            # copy is still running, so Windows refuses to overwrite the image.
            # The test is what the file SAYS rather than that it exists, because
            # the other way to land here is a source that cannot carry a
            # description at all, and that leaves a copy naming nothing -- a file
            # added to the venv for no benefit.  Undescribed, it goes.
            if self._is_ours(target):
                logger.info("Kept the existing %s launcher; could not refresh it", target.name)
                return str(target)
            self._discard(target)
            logger.warning("Not naming the %s process; launching unnamed", role, exc_info=True)
            return str(python_exe)
        return str(target)

    def prepare_launcher(self, role: str, python_exe: str | Path | None = None) -> None:
        """Make the copy this app's shortcut should start through NEXT time.

        An app's own process is the one case that cannot be named on the way in:
        naming it means writing a file with Python, and the process that would
        do the writing is the one being named.  So the shortcut prefers the copy
        when it is there and falls back to the plain interpreter when it is not,
        and each run makes it for the run after -- which costs one launch, once,
        and then heals itself for good.

        Defaults to the windowed interpreter beside the running one, because
        that is what a desktop app's shortcut starts: reading ``sys.executable``
        directly would name a copy after a copy on every run after the first.
        """
        source = Path(python_exe) if python_exe else Path(sys.executable).with_name("pythonw.exe")
        self.named_exe(source, role)

    def name_this_process(self, role: str, interpreter: str = "pythonw.exe") -> None:
        """Make the copy this app's launcher should start it through NEXT time.

        An app's own process is the one case that cannot be named on the way in:
        naming it means writing a file with Python, and the process that would
        do the writing is the one being named.  So the launcher prefers the copy
        when it is there and falls back to the plain interpreter when it is not,
        and each run makes it for the run after -- which costs one launch, once,
        and then heals itself for good.

        *interpreter* is the file name of the launcher the app is started
        through, beside the running one: the windowed ``pythonw.exe`` a shortcut
        starts, or ``python.exe`` for a launcher that redirects the app's output
        into a log.  By name, never ``sys.executable`` itself, because on every
        run after the first that IS the copy, and copying it would name a copy
        after a copy.

        Never raises.  `named_exe` falls back on the failures it can foresee,
        but this call sits at the top of an app's ``main()``, and there the
        failure nobody foresaw -- an interpreter Python could not locate, so
        ``sys.executable`` is empty -- is still not worth the window.  Every app
        wrapped the call in the same try/except for that reason; this is that
        wrapping, held once.  The failure is logged rather than swallowed: a
        task list full of anonymous Pythons with nothing anywhere saying why is
        the state this module exists to end.
        """
        try:
            self.named_exe(Path(sys.executable).with_name(interpreter), role)
        except Exception:
            logger.warning("Not naming this process (%s); launching unnamed", role, exc_info=True)

    # --- staying current ---

    def _source_stamp(self, source: Path, description: str) -> str:
        """What a copy has to match to still be current.

        Both halves matter: the interpreter's size and mtime catch a Python
        upgrade replacing the launcher underneath, and the description catches a
        change to what the app would write today -- a copy relabelled in code but
        not on disk keeps the old row heading for good otherwise.
        """
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
        """Whether *exe* is a copy this module stamped, whatever it says today.

        Asked by the private stamp field rather than by the label, so renaming
        what an app writes does not make it stop recognizing -- and start
        deleting -- copies it made itself.
        """
        if not exe.is_file():
            return False
        try:
            return self._read_field(exe, STAMP_FIELD) is not None
        except OSError:
            return False

    @staticmethod
    def _discard(target: Path) -> None:
        """Remove a copy that turned out to name nothing, if it can be removed."""
        try:
            if target.is_file():
                target.unlink()
        except OSError:
            logger.info("Left %s behind; it could not be removed", target.name, exc_info=True)

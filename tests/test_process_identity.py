"""The named interpreters an app's processes are started through."""
from __future__ import annotations

import ctypes
import re
import shutil
import struct
import sys
from ctypes import wintypes
from pathlib import Path

import pytest

from app_support.process_identity import (
    STAMP_FIELD,
    ProcessNamer,
    build_icon_resources,
    exe_prefix,
    read_version_field,
)

# Stamping runs UpdateResource, which only works on a real PE, so the Windows
# tier below exercises an actual interpreter -- the one the suite is running
# under, copied somewhere disposable.
REAL_INTERPRETER = Path(sys.executable)


class _FakeResources:
    """The two Win32 resource calls as a recording fake.

    What ``stamp`` wrote is what ``read_field`` answers, which is exactly the
    contract the real pair keeps -- so the keep/refresh/discard decisions can be
    pinned on any platform, with the Windows tier left to prove the real pair
    honours it. ``fails`` stands in for a source that cannot carry a
    description: a shim, a shell wrapper, anything that is not a PE.
    """

    def __init__(self, *, fails: bool = False) -> None:
        self.stamped: dict[Path, dict[str, str]] = {}
        self.stamp_calls = 0
        self.fails = fails

    def stamp(self, exe: Path, *, fields: dict[str, str], icon: bytes | None) -> None:
        self.stamp_calls += 1
        if self.fails:
            raise OSError("this file cannot carry a version resource")
        self.stamped[Path(exe)] = dict(fields)

    def read_field(self, exe: Path, field: str) -> str | None:
        fields = self.stamped.get(Path(exe))
        return None if fields is None else fields.get(field)


def _stub_interpreter(tmp_path: Path, name: str = "pythonw.exe") -> Path:
    """A stand-in interpreter for decision tests: the fake never inspects it,
    so a few bytes in the right place beat copying a real one."""
    exe = tmp_path / ".venv" / "Scripts" / name
    exe.parent.mkdir(parents=True, exist_ok=True)
    exe.write_bytes(b"MZ stub interpreter")
    return exe


def _interpreter(tmp_path: Path, name: str = "pythonw.exe") -> Path:
    exe = tmp_path / ".venv" / "Scripts" / name
    exe.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(REAL_INTERPRETER, exe)
    return exe


def _icon(tmp_path: Path) -> Path:
    """A minimal two-frame .ico -- enough to index, not a real picture."""
    first, second = b"\x01" * 40, b"\x02" * 60
    header = struct.pack("<HHH", 0, 1, 2)
    offset = len(header) + 32
    entries = (struct.pack("<BBBBHHLL", 16, 16, 0, 0, 1, 32, len(first), offset)
               + struct.pack("<BBBBHHLL", 32, 32, 0, 0, 1, 32, len(second), offset + len(first)))
    path = tmp_path / "app.ico"
    path.write_bytes(header + entries + first + second)
    return path


class TestExePrefix:
    def test_squashes_a_display_name_into_something_a_file_can_be_called(self):
        assert exe_prefix("Fun Time") == "FunTime-"
        assert exe_prefix("Highdeas") == "Highdeas-"

    def test_refuses_a_name_with_nothing_usable_in_it(self):
        with pytest.raises(ValueError):
            exe_prefix("   ")


class TestNaming:
    def test_names_the_copy_for_its_app_and_role(self):
        namer = ProcessNamer("Fun Time")
        assert namer.exe_name("pythonw.exe", "AudioCompanion") == "FunTime-AudioCompanion.exe"

    def test_keeps_the_interpreter_suffix_rather_than_assuming_one(self):
        # Taking the suffix from the source keeps a console interpreter and a
        # windowed one from being told apart by anything but which was copied.
        assert ProcessNamer("Genau").exe_name("python.exe", "Genau").endswith(".exe")

    @pytest.mark.parametrize("role", ["Audio Companion", "audio-companion", "../evil", "", "Nau2"])
    def test_refuses_a_role_that_is_not_plain_letters(self, role: str):
        # The role becomes a file name beside the interpreter, so anything with
        # a separator in it is a write somewhere nobody asked for.
        with pytest.raises(ValueError):
            ProcessNamer("Fun Time").exe_name("pythonw.exe", role)

    def test_the_description_leads_with_the_app(self):
        # This string, not the file name, is what the Processes tab displays.
        assert ProcessNamer("Fun Time").description("Nau") == "Fun Time – Nau"

    def test_the_description_splits_the_role_back_into_words(self):
        assert ProcessNamer("Fun Time").description("AudioCompanion") == "Fun Time – Audio Companion"

    def test_a_lone_app_does_not_say_its_name_twice(self):
        # Most apps have one window and one role, named after themselves.
        assert ProcessNamer("Highdeas").description("Highdeas") == "Highdeas"

    def test_a_lone_app_whose_name_is_two_words_run_together(self):
        # The role has to be one word to be a file name; the app name does not.
        # Comparing the split role against the app name made PromptCrafter's own
        # role a different thing from PromptCrafter: "PromptCrafter - Prompt
        # Crafter".
        assert ProcessNamer("PromptCrafter").description("PromptCrafter") == "PromptCrafter"
        assert ProcessNamer("Genau VR").description("GenauVR") == "Genau VR"

    def test_an_acronym_in_a_role_stays_whole(self):
        # Breaking at every capital spelled "GenauVR" out as "Genau V R", which
        # then no longer matched the app's own name -- so the row read
        # "Genau VR - Genau V R" instead of just "Genau VR".
        assert ProcessNamer("Genau VR").description("GenauVR") == "Genau VR"
        assert ProcessNamer("Fun Time").description("RFBWindow") == "Fun Time – RFB Window"


class TestBuildIconResources:
    def test_reindexes_the_directory_onto_resource_ids(self, tmp_path: Path):
        """An .ico indexes its images by byte offset and a PE indexes them by
        resource id, so only the directory is rebuilt."""
        images, directory = build_icon_resources(_icon(tmp_path).read_bytes())

        assert len(images) == 2
        assert struct.unpack_from("<HHH", directory, 0) == (0, 1, 2)
        ids = [struct.unpack_from("<H", directory, 6 + i * 14 + 12)[0] for i in range(2)]
        assert ids == [1, 2]

    def test_refuses_something_that_is_not_an_icon(self):
        with pytest.raises(ValueError):
            build_icon_resources(b"\x89PNG\r\n\x1a\n" + b"\x00" * 32)


class TestNamedExe:
    def test_copies_the_interpreter_to_a_role_named_sibling(self, tmp_path: Path):
        # A sibling, not a copy elsewhere: pyvenv.cfg is found one directory up
        # from the interpreter, so anywhere but Scripts/ is a different (or no)
        # virtualenv, with the app's own imports failing.
        source = _stub_interpreter(tmp_path)
        resources = _FakeResources()

        result = Path(ProcessNamer("Fun Time", stamp=resources.stamp,
                                   read_field=resources.read_field)
                      .named_exe(source, "Portrait"))

        assert result == source.with_name("FunTime-Portrait.exe")
        assert result.read_bytes() == source.read_bytes()

    def test_the_copy_describes_itself(self, tmp_path: Path):
        """The whole point: the Processes tab reads the file description, so a
        copy that is merely renamed still shows up as one more "Python"."""
        source = _interpreter(tmp_path)

        result = Path(ProcessNamer("Highdeas").named_exe(source, "Highdeas"))

        assert read_version_field(result, "FileDescription") == "Highdeas"
        assert read_version_field(result, "ProductName") == "Highdeas"
        assert read_version_field(result, STAMP_FIELD)

    def test_copies_it_beside_the_source_so_the_venv_still_resolves(self, tmp_path: Path):
        # pyvenv.cfg is found one directory up from the interpreter, so a copy
        # anywhere but Scripts/ is a different (or no) virtualenv -- with the
        # app's site-packages missing and every import of its own failing.
        source = _interpreter(tmp_path)

        result = Path(ProcessNamer("Clipper").named_exe(source, "Clipper"))

        assert result.parent == source.parent

    def test_keeps_the_interpreters_own_application_manifest(self, tmp_path: Path):
        """Rewriting resources must not cost the manifest that comes with them:
        it carries the DPI awareness every window the app opens inherits, so
        losing it would rescale the app to make a task list readable."""
        source = _interpreter(tmp_path)

        result = Path(ProcessNamer("Evolver").named_exe(source, "Evolver"))

        assert _has_manifest(result), "the copy lost its application manifest"

    def test_stamps_the_icon_when_the_app_has_one(self, tmp_path: Path):
        source = _interpreter(tmp_path)
        namer = ProcessNamer("Scripture", icon=_icon(tmp_path))

        result = Path(namer.named_exe(source, "Scripture"))

        assert _has_resource(result, kind=14, name=1), "no icon directory in the copy"

    def test_works_for_an_app_with_no_icon_at_all(self, tmp_path: Path):
        source = _interpreter(tmp_path)

        result = Path(ProcessNamer("Scripture").named_exe(source, "Scripture"))

        assert read_version_field(result, "FileDescription") == "Scripture"

    def test_reuses_a_copy_that_is_already_current(self, tmp_path: Path):
        # Asked on every launch, and the answer has to be "already there" -- a
        # copy judged stale on its own would rewrite a running image every run
        # and be refused for it.
        source = _stub_interpreter(tmp_path)
        resources = _FakeResources()
        namer = ProcessNamer("Genau", stamp=resources.stamp,
                             read_field=resources.read_field)
        first = Path(namer.named_exe(source, "Genau"))

        assert Path(namer.named_exe(source, "Genau")) == first
        assert resources.stamp_calls == 1

    def test_refreshes_a_copy_made_from_an_older_interpreter(self, tmp_path: Path):
        # A Python upgrade replaces the launcher underneath.  A copy that keeps
        # running the old one is an app on an interpreter nobody installed.
        source = _stub_interpreter(tmp_path)
        resources = _FakeResources()
        namer = ProcessNamer("Genau", stamp=resources.stamp,
                             read_field=resources.read_field)
        stale = Path(namer.named_exe(source, "Landscape"))
        source.write_bytes(b"MZ the upgrade's launcher, longer than before")

        namer.named_exe(source, "Landscape")

        assert stale.read_bytes() == source.read_bytes()
        assert resources.stamped[stale]["FileDescription"] == "Genau – Landscape"

    def test_refreshes_a_copy_whose_label_this_version_no_longer_writes(self, tmp_path: Path):
        """The stamp records the label as well as the interpreter, because a
        copy relabelled in code but not on disk would keep the old row heading
        for good -- the file is still current by every other measure."""
        source = _stub_interpreter(tmp_path)
        resources = _FakeResources()
        ProcessNamer("Old Name", stamp=resources.stamp,
                     read_field=resources.read_field).named_exe(source, "Dashboard")
        # The same prefix with a different label: the file name cannot tell them
        # apart, so only the recorded stamp can.
        result = Path(ProcessNamer("OldName", stamp=resources.stamp,
                                   read_field=resources.read_field)
                      .named_exe(source, "Dashboard"))

        assert resources.stamped[result]["FileDescription"] == "OldName – Dashboard"

    def test_falls_back_to_the_interpreter_when_the_copy_cannot_be_made(self, tmp_path: Path):
        # A read-only venv, an antivirus hold, a full disk.  Naming a process is
        # never worth failing a launch over: the app comes up anonymous.
        source = _stub_interpreter(tmp_path)
        source.with_name("Broker-Broker.exe").mkdir()  # the copy cannot land there
        resources = _FakeResources()

        assert ProcessNamer("Broker", stamp=resources.stamp,
                            read_field=resources.read_field) \
            .named_exe(source, "Broker") == str(source)

    def test_falls_back_when_the_interpreter_cannot_carry_a_description(self, tmp_path: Path):
        """Stamping needs a real executable.  Anything else -- a shim, a shell
        wrapper -- loses only its name, and a launch that would have worked
        still works."""
        source = _stub_interpreter(tmp_path)
        resources = _FakeResources(fails=True)

        assert ProcessNamer("Broker", stamp=resources.stamp,
                            read_field=resources.read_field) \
            .named_exe(source, "Broker") == str(source)

    def test_leaves_nothing_behind_when_it_cannot_describe_the_copy(self, tmp_path: Path):
        # A copy that names nothing is a file added to the venv for no benefit,
        # and a launcher pointed at it would report a process it cannot identify.
        source = _stub_interpreter(tmp_path)
        resources = _FakeResources(fails=True)

        ProcessNamer("Broker", stamp=resources.stamp,
                     read_field=resources.read_field).named_exe(source, "Broker")

        assert not source.with_name("Broker-Broker.exe").exists()

    def test_keeps_a_copy_it_could_not_refresh_rather_than_dropping_the_name(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ):
        # The usual reason a refresh fails is that the last run's copy is still
        # running and Windows will not overwrite a running image.  One label
        # behind beats going back to an unidentifiable process.
        source = _stub_interpreter(tmp_path)
        resources = _FakeResources()
        existing = Path(ProcessNamer("Clipper", stamp=resources.stamp,
                                     read_field=resources.read_field)
                        .named_exe(source, "Clipper"))
        source.write_bytes(b"MZ upgraded underneath, so a refresh is wanted")
        monkeypatch.setattr(
            "app_support.process_identity.shutil.copyfile",
            lambda *a, **k: (_ for _ in ()).throw(PermissionError("in use")),
        )

        # The refresh cannot happen, and what is there is one of ours -- so it
        # is kept rather than leaving the process anonymous.
        assert ProcessNamer("Clipper", stamp=resources.stamp,
                            read_field=resources.read_field) \
            .named_exe(source, "Clipper") == str(existing)
        assert resources.stamped[existing]["FileDescription"] == "Clipper"

    def test_falls_back_rather_than_raising_on_a_role_it_cannot_name(self, tmp_path: Path):
        # A launch site is not a validation site: a bad role loses the name, not
        # the window.
        source = _stub_interpreter(tmp_path)
        resources = _FakeResources()

        assert ProcessNamer("Broker", stamp=resources.stamp,
                            read_field=resources.read_field) \
            .named_exe(source, "Bad Role") == str(source)


class TestPrepareLauncher:
    def test_names_the_windowed_interpreter_beside_the_running_one(self, tmp_path: Path):
        """An app's shortcut starts pythonw, so that is the file to copy -- and
        naming it from sys.executable would name a copy after a copy on every
        run after the first."""
        source = _stub_interpreter(tmp_path)
        resources = _FakeResources()

        ProcessNamer("Highdeas", stamp=resources.stamp,
                     read_field=resources.read_field) \
            .prepare_launcher("Highdeas", source)

        assert source.with_name("Highdeas-Highdeas.exe").is_file()


class TestProcessNamePattern:
    def test_matches_the_copies_the_app_launches_under(self):
        pattern = ProcessNamer("Fun Time").process_name_pattern
        assert re.match(pattern, "FunTime-Portrait.exe")
        assert re.match(pattern, "FunTime-AudioCompanion.exe")

    def test_still_matches_a_plain_interpreter(self):
        # The copy is best-effort, so a process can still arrive under the plain
        # interpreter and must stay reachable.
        pattern = ProcessNamer("Fun Time").process_name_pattern
        assert all(re.match(pattern, name) for name in ("pythonw.exe", "python.exe", "py.exe"))

    def test_leaves_everything_else_alone(self):
        # Sweeps force-kill what they match, so a pattern that reaches one of
        # the user's own apps -- or another of his -- is the worst failure this
        # module can have.
        pattern = ProcessNamer("Fun Time").process_name_pattern
        for name in ("notepad.exe", "mypythonw.exe", "FunTimeOther.exe", "Genau-Nau.exe"):
            assert not re.match(pattern, name), name


def _has_resource(exe: Path, *, kind: int, name: int) -> bool:
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.LoadLibraryExW.restype = wintypes.HMODULE
    k32.LoadLibraryExW.argtypes = [wintypes.LPCWSTR, wintypes.HANDLE, wintypes.DWORD]
    k32.FindResourceW.restype = wintypes.HANDLE
    k32.FindResourceW.argtypes = [wintypes.HMODULE, ctypes.c_void_p, ctypes.c_void_p]
    k32.FreeLibrary.argtypes = [wintypes.HMODULE]
    module = k32.LoadLibraryExW(str(exe), None, 0x00000002)  # LOAD_LIBRARY_AS_DATAFILE
    if not module:
        return False
    try:
        return bool(k32.FindResourceW(module, ctypes.c_void_p(name), ctypes.c_void_p(kind)))
    finally:
        k32.FreeLibrary(module)


def _has_manifest(exe: Path) -> bool:
    return _has_resource(exe, kind=24, name=1)

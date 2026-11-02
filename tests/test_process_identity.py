from __future__ import annotations

import ctypes
import logging
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
    def __init__(self, *, fails: bool = False, raising: Exception | None = None) -> None:
        self.stamped: dict[Path, dict[str, str]] = {}
        self.stamp_calls = 0
        self.fails = fails
        self.raising = raising

    def stamp(self, exe: Path, *, fields: dict[str, str], icon: bytes | None) -> None:
        self.stamp_calls += 1
        if self.raising is not None:
            raise self.raising
        if self.fails:
            raise OSError("this file cannot carry a version resource")
        self.stamped[Path(exe)] = dict(fields)

    def read_field(self, exe: Path, field: str) -> str | None:
        fields = self.stamped.get(Path(exe))
        return None if fields is None else fields.get(field)


def _stub_interpreter(tmp_path: Path, name: str = "pythonw.exe") -> Path:
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
        with pytest.raises(ValueError, match="app name has nothing to make a file name from"):
            exe_prefix("   ")

    @pytest.mark.parametrize("app_name", ["Fun Time", "Highdeas", "OSR2 Broker!", "a.b*c"])
    def test_never_holds_a_character_a_regex_would_read(self, app_name: str):
        assert re.fullmatch(r"[A-Za-z0-9]+-", exe_prefix(app_name)), app_name


class TestNaming:
    def test_names_the_copy_for_its_app_and_role(self):
        namer = ProcessNamer("Fun Time")
        assert namer.exe_name("pythonw.exe", "AudioCompanion") == "FunTime-AudioCompanion.exe"

    def test_keeps_the_interpreter_suffix_rather_than_assuming_one(self):
        assert ProcessNamer("Genau").exe_name("python.com", "Genau").endswith(".com")

    @pytest.mark.parametrize("role", ["Audio Companion", "audio-companion", "../evil", "", "MainFunestra2"])
    def test_refuses_a_role_that_is_not_plain_letters(self, role: str):
        with pytest.raises(ValueError, match="role must be plain letters"):
            ProcessNamer("Fun Time").exe_name("pythonw.exe", role)

    def test_the_description_leads_with_the_app(self):
        assert ProcessNamer("Fun Time").description("MainFunestra") == "Fun Time – Main Funestra"

    def test_the_description_splits_the_role_back_into_words(self):
        assert ProcessNamer("Fun Time").description("AudioCompanion") == "Fun Time – Audio Companion"

    def test_a_lone_app_does_not_say_its_name_twice(self):
        assert ProcessNamer("Highdeas").description("Highdeas") == "Highdeas"

    def test_a_lone_app_whose_name_is_two_words_run_together(self):
        assert ProcessNamer("PromptCrafter").description("PromptCrafter") == "PromptCrafter"
        assert ProcessNamer("Genau VR").description("GenauVR") == "Genau VR"

    def test_an_acronym_in_a_role_stays_whole(self):
        assert ProcessNamer("Genau VR").description("GenauVR") == "Genau VR"
        assert ProcessNamer("Fun Time").description("RFBWindow") == "Fun Time – RFB Window"


class TestBuildIconResources:
    def test_reindexes_the_directory_onto_resource_ids(self, tmp_path: Path):
        images, directory = build_icon_resources(_icon(tmp_path).read_bytes())

        assert len(images) == 2
        assert struct.unpack_from("<HHH", directory, 0) == (0, 1, 2)
        ids = [struct.unpack_from("<H", directory, 6 + i * 14 + 12)[0] for i in range(2)]
        assert ids == [1, 2]

    def test_refuses_something_that_is_not_an_icon(self):
        with pytest.raises(ValueError, match="not an icon file"):
            build_icon_resources(b"\x89PNG\r\n\x1a\n" + b"\x00" * 32)


class TestNamedExe:
    def test_copies_the_interpreter_to_a_role_named_sibling(self, tmp_path: Path):
        # CPython finds pyvenv.cfg one directory up from the interpreter, so only a sibling stays in the virtualenv.
        source = _stub_interpreter(tmp_path)
        resources = _FakeResources()

        result = Path(ProcessNamer("Fun Time", stamp=resources.stamp,
                                   read_field=resources.read_field)
                      .named_exe(source, "Portrait"))

        assert result == source.with_name("FunTime-Portrait.exe")
        assert result.read_bytes() == source.read_bytes()

    def test_the_copy_describes_itself(self, tmp_path: Path):
        source = _interpreter(tmp_path)

        result = Path(ProcessNamer("Highdeas").named_exe(source, "Highdeas"))

        assert read_version_field(result, "FileDescription") == "Highdeas"
        assert read_version_field(result, "ProductName") == "Highdeas"
        assert read_version_field(result, STAMP_FIELD)

    def test_keeps_the_interpreters_own_application_manifest(self, tmp_path: Path):
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
        source = _stub_interpreter(tmp_path)
        resources = _FakeResources()
        namer = ProcessNamer("Genau", stamp=resources.stamp,
                             read_field=resources.read_field)
        first = Path(namer.named_exe(source, "Genau"))

        assert Path(namer.named_exe(source, "Genau")) == first
        assert resources.stamp_calls == 1

    def test_refreshes_a_copy_made_from_an_older_interpreter(self, tmp_path: Path):
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
        source = _stub_interpreter(tmp_path)
        resources = _FakeResources()
        ProcessNamer("Old Name", stamp=resources.stamp,
                     read_field=resources.read_field).named_exe(source, "Dashboard")
        result = Path(ProcessNamer("OldName", stamp=resources.stamp,
                                   read_field=resources.read_field)
                      .named_exe(source, "Dashboard"))

        assert resources.stamped[result]["FileDescription"] == "OldName – Dashboard"

    def test_falls_back_to_the_interpreter_when_the_copy_cannot_be_made(self, tmp_path: Path):
        source = _stub_interpreter(tmp_path)
        source.with_name("Broker-Broker.exe").mkdir()
        resources = _FakeResources()

        assert ProcessNamer("Broker", stamp=resources.stamp,
                            read_field=resources.read_field) \
            .named_exe(source, "Broker") == str(source)

    def test_falls_back_when_the_interpreter_cannot_carry_a_description(self, tmp_path: Path):
        source = _stub_interpreter(tmp_path)
        resources = _FakeResources(fails=True)

        assert ProcessNamer("Broker", stamp=resources.stamp,
                            read_field=resources.read_field) \
            .named_exe(source, "Broker") == str(source)

    def test_leaves_no_copy_when_it_cannot_describe_one(self, tmp_path: Path):
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
        # out of date beats going back to an unidentifiable process.
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

        assert ProcessNamer("Clipper", stamp=resources.stamp,
                            read_field=resources.read_field) \
            .named_exe(source, "Clipper") == str(existing)
        assert resources.stamped[existing]["FileDescription"] == "Clipper"

    @pytest.mark.parametrize("failure", [
        struct.error("unpack_from requires a buffer of at least 6 bytes"),
        AttributeError("module 'ctypes' has no attribute 'WinDLL'"),
        RuntimeError("anything else the resource API can say"),
    ], ids=["a truncated icon", "no Win32 resource API", "anything else"])
    def test_never_raises_however_the_stamp_fails(self, tmp_path: Path, failure):
        source = _stub_interpreter(tmp_path)
        resources = _FakeResources(raising=failure)

        assert ProcessNamer("Broker", stamp=resources.stamp,
                            read_field=resources.read_field) \
            .named_exe(source, "Broker") == str(source)
        assert not source.with_name("Broker-Broker.exe").exists()

    def test_falls_back_rather_than_raising_on_a_role_it_cannot_name(self, tmp_path: Path):
        source = _stub_interpreter(tmp_path)
        resources = _FakeResources()

        assert ProcessNamer("Broker", stamp=resources.stamp,
                            read_field=resources.read_field) \
            .named_exe(source, "Bad Role") == str(source)


class TestNameThisProcess:
    def _launchers(self, tmp_path: Path) -> tuple[Path, Path]:
        console = _stub_interpreter(tmp_path, "python.exe")
        windowed = _stub_interpreter(tmp_path, "pythonw.exe")
        windowed.write_bytes(b"MZ the windowed launcher, told apart by its bytes")
        return console, windowed

    def test_copies_the_windowed_launcher_beside_the_running_one_by_default(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ):
        console, windowed = self._launchers(tmp_path)
        monkeypatch.setattr(sys, "executable", str(console))
        resources = _FakeResources()

        ProcessNamer("Highdeas", stamp=resources.stamp,
                     read_field=resources.read_field).name_this_process("Highdeas")

        assert console.with_name("Highdeas-Highdeas.exe").read_bytes() == windowed.read_bytes()

    def test_copies_the_console_launcher_when_that_is_what_starts_the_app(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ):
        console, windowed = self._launchers(tmp_path)
        monkeypatch.setattr(sys, "executable", str(windowed))
        resources = _FakeResources()

        ProcessNamer("Highdeas", stamp=resources.stamp, read_field=resources.read_field) \
            .name_this_process("Highdeas", interpreter="python.exe")

        assert console.with_name("Highdeas-Highdeas.exe").read_bytes() == console.read_bytes()

    def test_never_raises_when_python_cannot_say_what_it_is_running_under(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
    ):
        monkeypatch.setattr(sys, "executable", "")
        resources = _FakeResources()

        with caplog.at_level(logging.WARNING, logger="app_support.process_identity"):
            ProcessNamer("Highdeas", stamp=resources.stamp,
                         read_field=resources.read_field).name_this_process("Highdeas")

        (record,) = caplog.records
        assert "Highdeas" in record.getMessage()
        assert record.exc_info, "the warning says something failed but not what"


class TestProcessNamePattern:
    def test_carries_the_prefix_the_way_the_copies_spell_it(self):
        namer = ProcessNamer("Fun Time")
        assert namer.prefix in namer.process_name_pattern

    def test_matches_the_copies_the_app_launches_under(self):
        pattern = ProcessNamer("Fun Time").process_name_pattern
        assert re.match(pattern, "FunTime-Portrait.exe")
        assert re.match(pattern, "FunTime-AudioCompanion.exe")

    def test_still_matches_a_plain_interpreter(self):
        pattern = ProcessNamer("Fun Time").process_name_pattern
        assert all(re.match(pattern, name) for name in ("pythonw.exe", "python.exe", "py.exe"))

    def test_leaves_everything_else_alone(self):
        pattern = ProcessNamer("Fun Time").process_name_pattern
        for name in ("notepad.exe", "mypythonw.exe", "FunTimeOther.exe", "Genau-MainFunestra.exe"):
            assert not re.match(pattern, name), name


class TestOwnsExeName:
    NAMER = ProcessNamer("Fun Time")

    def test_recognizes_its_own_copies_whatever_their_case(self):
        assert self.NAMER.owns_exe_name("FunTime-Dashboard.exe")
        assert self.NAMER.owns_exe_name("funtime-dashboard.exe")

    def test_answers_for_exactly_the_names_it_gives_its_copies(self):
        for role in ("Dashboard", "AudioCompanion", "MainFunestra"):
            name = self.NAMER.exe_name("pythonw.exe", role)
            assert self.NAMER.owns_exe_name(name), name

    def test_does_not_claim_the_interpreters_a_copy_falls_back_to(self):
        for name in ("pythonw.exe", "python.exe", "py.exe"):
            assert not self.NAMER.owns_exe_name(name), name

    def test_does_not_claim_a_name_that_merely_starts_the_same(self):
        for name in ("FunTimeSetup.msi", "FunTimeOther.exe", "Genau-MainFunestra.exe", "notepad.exe"):
            assert not self.NAMER.owns_exe_name(name), name


def _has_resource(exe: Path, *, kind: int, name: int) -> bool:
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.LoadLibraryExW.restype = wintypes.HMODULE
    k32.LoadLibraryExW.argtypes = [wintypes.LPCWSTR, wintypes.HANDLE, wintypes.DWORD]
    k32.FindResourceW.restype = wintypes.HANDLE
    k32.FindResourceW.argtypes = [wintypes.HMODULE, ctypes.c_void_p, ctypes.c_void_p]
    k32.FreeLibrary.argtypes = [wintypes.HMODULE]
    module = k32.LoadLibraryExW(str(exe), None, 0x00000002)  # Win32 LOAD_LIBRARY_AS_DATAFILE
    if not module:
        return False
    try:
        return bool(k32.FindResourceW(module, ctypes.c_void_p(name), ctypes.c_void_p(kind)))
    finally:
        k32.FreeLibrary(module)


def _has_manifest(exe: Path) -> bool:
    return _has_resource(exe, kind=24, name=1)

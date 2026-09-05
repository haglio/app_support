"""Reading a JSON config: paths hang off the file's own directory, and every
refusal names the dotted key and the file."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from app_support.config_reader import (
    optional_section,
    read_json_config,
    require_path,
    require_section,
    require_typed,
    require_value,
    resolve_path,
)

SOURCE = Path("C:/example/config.json")


class TestReadJsonConfig:
    def test_a_relative_path_hangs_off_the_default_directory(self, tmp_path: Path):
        (tmp_path / "config.json").write_text(json.dumps({"a": 1}), encoding="utf-8")

        path, data = read_json_config(Path("config.json"), default_dir=tmp_path)

        assert path == (tmp_path / "config.json").resolve()
        assert data == {"a": 1}

    def test_a_missing_file_is_named(self, tmp_path: Path):
        with pytest.raises(FileNotFoundError, match=r"config\.json"):
            read_json_config(tmp_path / "config.json", default_dir=tmp_path)


class TestResolvePath:
    def test_an_absolute_path_is_taken_as_given(self, tmp_path: Path):
        assert resolve_path(tmp_path, tmp_path / "state") == tmp_path / "state"

    def test_a_relative_path_hangs_off_the_base(self, tmp_path: Path):
        assert resolve_path(tmp_path, "state") == (tmp_path / "state").resolve()


class TestRequireSection:
    def test_the_object_comes_back(self):
        assert require_section({"paths": {"a": 1}}, "paths", SOURCE) == {"a": 1}

    def test_a_missing_section_names_itself_and_the_file(self):
        with pytest.raises(ValueError, match=r"config\.paths \(in .*config\.json\)"):
            require_section({}, "paths", SOURCE)

    def test_a_section_that_is_not_an_object_is_refused(self):
        with pytest.raises(TypeError, match=r"config\.paths"):
            require_section({"paths": "C:/x"}, "paths", SOURCE)

    def test_the_context_says_where_in_the_file(self):
        with pytest.raises(ValueError, match=r"config\.paths\.nau"):
            require_section({}, "nau", SOURCE, context="config.paths")


class TestOptionalSection:
    def test_absent_is_none_and_present_is_the_object(self):
        assert optional_section({}, "vr", SOURCE) is None
        assert optional_section({"vr": {"a": 1}}, "vr", SOURCE) == {"a": 1}

    def test_present_but_not_an_object_is_still_refused(self):
        with pytest.raises(TypeError, match="vr"):
            optional_section({"vr": 3}, "vr", SOURCE)


class TestRequireValue:
    def test_a_missing_value_names_itself_and_the_file(self):
        with pytest.raises(ValueError, match=r"config\.paths\.ahk_exe \(in .*config\.json\)"):
            require_value({}, "ahk_exe", SOURCE, context="config.paths")

    def test_a_path_is_resolved_against_the_base(self, tmp_path: Path):
        assert require_path({"state_dir": "state"}, "state_dir", SOURCE, base=tmp_path) == (
            (tmp_path / "state").resolve())

    def test_a_typed_value_goes_through_the_cast(self):
        assert require_typed({"port": "50557"}, "port", SOURCE, cast=int) == 50557

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from app_support import haglio_settings


def _settings(path: Path, data: dict) -> Path:
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def test_every_app_reads_a_setting_from_the_one_file(tmp_path, monkeypatch):
    monkeypatch.setenv(haglio_settings.SETTINGS_ENV,
                       str(_settings(tmp_path / "settings.json", {"library_root": "D:/library"})))

    assert haglio_settings.value("library_root") == "D:/library"


def test_the_one_file_is_in_the_haglio_folder_of_the_home_folder(tmp_path, monkeypatch):
    monkeypatch.delenv(haglio_settings.SETTINGS_ENV, raising=False)
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    (tmp_path / ".haglio").mkdir()
    _settings(tmp_path / ".haglio" / "settings.json", {"library_root": "D:/library"})

    assert haglio_settings.value("library_root") == "D:/library"


def test_a_machine_with_no_settings_file_runs_on_the_example(tmp_path, monkeypatch):
    monkeypatch.setenv(haglio_settings.SETTINGS_ENV, str(tmp_path / "absent.json"))

    assert haglio_settings.value("library_root") == haglio_settings.EXAMPLE["library_root"]


def test_a_setting_the_file_lacks_is_named_with_the_file(tmp_path, monkeypatch):
    settings = _settings(tmp_path / "settings.json", {"genau_flick_words": {"one": "flick"}})
    monkeypatch.setenv(haglio_settings.SETTINGS_ENV, str(settings))

    with pytest.raises(haglio_settings.MissingSetting) as missing:
        haglio_settings.value("genau_flick_words", "many")

    assert "genau_flick_words -> many" in str(missing.value)
    assert str(settings) in str(missing.value)


def test_a_suite_on_a_machine_with_real_settings_asks_for_the_example(tmp_path, monkeypatch):
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    (tmp_path / ".haglio").mkdir()
    _settings(tmp_path / ".haglio" / "settings.json", {"library_root": "D:/library"})
    monkeypatch.setenv(haglio_settings.SETTINGS_ENV, haglio_settings.THE_EXAMPLE)

    assert haglio_settings.load() == haglio_settings.EXAMPLE


def test_one_reader_changing_what_it_was_handed_changes_nobody_else_s(monkeypatch):
    monkeypatch.setenv(haglio_settings.SETTINGS_ENV, haglio_settings.THE_EXAMPLE)

    haglio_settings.load()["genau_flick_words"]["one"] = "changed"

    assert haglio_settings.value("genau_flick_words", "one") == "flick"


@pytest.mark.parametrize("setting", ["microphone", "vosk_model"])
def test_the_example_names_what_every_app_that_listens_hears_with(setting, monkeypatch):
    monkeypatch.setenv(haglio_settings.SETTINGS_ENV, haglio_settings.THE_EXAMPLE)

    assert isinstance(haglio_settings.value(setting), str)
    assert haglio_settings.value(setting)


FOLDERS_THE_APPS_READ = (
    "genau_dir",
    "kino_dir",
    "genau_audio_dir",
    "origenerator_images_dir",
    "origenerator_videos_dir",
    "origenerator_scripts_dir",
    "origenerator_audio_dir",
    "warm_gun_journal_dir",
    "funscript_corpus_dir",
)


@pytest.mark.parametrize("setting", FOLDERS_THE_APPS_READ)
def test_the_example_has_each_folder_an_app_reads_inside_its_library_root(setting, monkeypatch):
    monkeypatch.setenv(haglio_settings.SETTINGS_ENV, haglio_settings.THE_EXAMPLE)

    assert haglio_settings.value(setting).startswith(haglio_settings.value("library_root") + "/")


def test_the_checkouts_are_found_in_the_folders_the_settings_name_in_order(tmp_path, monkeypatch):
    monkeypatch.setenv(haglio_settings.SETTINGS_ENV, str(_settings(
        tmp_path / "settings.json",
        {"library_root": "L:/library", "project_roots": ["W:/workspace", "L:/library/projects"]})))

    assert haglio_settings.project_roots() == (Path("W:/workspace"), Path("L:/library/projects"))


def test_settings_naming_no_checkout_folders_mean_the_librarys_projects_folder_the_repos_lived_in_before(
        tmp_path, monkeypatch):
    monkeypatch.setenv(haglio_settings.SETTINGS_ENV,
                       str(_settings(tmp_path / "settings.json", {"library_root": "L:/library"})))

    assert haglio_settings.project_roots() == (Path("L:/library/projects"),)


def test_many_readers_read_the_file_once_until_its_date_changes(tmp_path, monkeypatch):
    settings = _settings(tmp_path / "settings.json", {"library_root": "D:/one"})
    monkeypatch.setenv(haglio_settings.SETTINGS_ENV, str(settings))
    dated = settings.stat().st_mtime_ns - 10_000_000_000
    os.utime(settings, ns=(dated, dated))
    parsed = []
    real_loads = haglio_settings.json.loads
    monkeypatch.setattr(haglio_settings.json, "loads", lambda text: parsed.append(text) or real_loads(text))

    first = [haglio_settings.value("library_root") for _ in range(5)]
    _settings(settings, {"library_root": "D:/two"})
    os.utime(settings, ns=(dated, dated + 1_000_000_000))
    after_the_change = [haglio_settings.value("library_root") for _ in range(5)]

    assert first == ["D:/one"] * 5
    assert after_the_change == ["D:/two"] * 5
    assert len(parsed) == 2


def test_a_test_runs_example_keeps_every_folder_inside_the_runs_own_folder(tmp_path):
    inside = haglio_settings.example_inside(tmp_path)

    assert haglio_settings.reaching_outside(inside, tmp_path) == []
    assert Path(inside["library_root"]).is_relative_to(tmp_path)
    assert inside["microphone"] == haglio_settings.EXAMPLE["microphone"]


def test_a_setting_naming_a_folder_elsewhere_is_named_as_reaching_outside(tmp_path):
    settings = haglio_settings.example_inside(tmp_path) | {
        "kino_dir": "C:/somewhere/else", "project_roots": [str(tmp_path / "checkouts"), "D:/workspace"]}

    assert haglio_settings.reaching_outside(settings, tmp_path) == ["project_roots", "kino_dir"]


def test_a_test_run_is_pointed_at_its_settings_by_a_file_in_its_own_folder(tmp_path):
    environ: dict[str, str] = {}

    haglio_settings.run_on(haglio_settings.example_inside(tmp_path), tmp_path, environ)

    written = Path(environ[haglio_settings.SETTINGS_ENV])
    assert written.parent == tmp_path
    assert json.loads(written.read_text(encoding="utf-8")) == haglio_settings.example_inside(tmp_path)

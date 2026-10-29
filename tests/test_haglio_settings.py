"""The settings all of Haglio shares, written once and read by every app.

Every value here is fabricated."""
from __future__ import annotations

import json
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


def test_a_settings_file_written_before_the_images_folder_was_renamed_reads_under_the_new_name(
        tmp_path, monkeypatch):
    monkeypatch.setenv(haglio_settings.SETTINGS_ENV, str(_settings(
        tmp_path / "settings.json",
        {"library_root": "D:/library", "origenerator_pictures_dir": "D:/library/images/origenerator"})))

    assert haglio_settings.value("origenerator_images_dir") == "D:/library/images/origenerator"
    assert haglio_settings.value("origenerator_pictures_dir") == "D:/library/images/origenerator"


def test_a_setting_the_file_lacks_is_named_with_the_file(tmp_path, monkeypatch):
    settings = _settings(tmp_path / "settings.json", {"genau_flick_words": {"one": "flick"}})
    monkeypatch.setenv(haglio_settings.SETTINGS_ENV, str(settings))

    with pytest.raises(haglio_settings.MissingSetting) as missing:
        haglio_settings.value("genau_flick_words", "many")

    assert "genau_flick_words -> many" in str(missing.value)
    assert str(settings) in str(missing.value)


def test_a_suite_on_a_machine_with_real_settings_asks_for_the_example(tmp_path, monkeypatch):
    """A suite runs as a public checkout does, never on the library's own settings."""
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    (tmp_path / ".haglio").mkdir()
    _settings(tmp_path / ".haglio" / "settings.json", {"library_root": "D:/library"})
    monkeypatch.setenv(haglio_settings.SETTINGS_ENV, haglio_settings.THE_EXAMPLE)

    assert haglio_settings.load() == haglio_settings.EXAMPLE


def test_one_reader_changing_what_it_was_handed_changes_nobody_else_s(monkeypatch):
    monkeypatch.setenv(haglio_settings.SETTINGS_ENV, haglio_settings.THE_EXAMPLE)

    haglio_settings.load()["genau_flick_words"]["one"] = "changed"

    assert haglio_settings.value("genau_flick_words", "one") == "flick"


FOLDERS_THE_APPS_READ = (
    "genau_dir",
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


def test_settings_naming_no_checkout_folders_mean_the_projects_folder_in_the_library(tmp_path, monkeypatch):
    monkeypatch.setenv(haglio_settings.SETTINGS_ENV,
                       str(_settings(tmp_path / "settings.json", {"library_root": "L:/library"})))

    assert haglio_settings.project_roots() == (Path("L:/library/projects"),)

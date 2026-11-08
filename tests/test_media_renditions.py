from __future__ import annotations

import json
from pathlib import Path

import pytest

from app_support import haglio_settings
from app_support.media_renditions import original_rendition, renditions


@pytest.fixture
def kino(tmp_path: Path, monkeypatch) -> Path:
    kino = tmp_path / "videos" / "kino"
    settings = tmp_path / "settings.json"
    settings.write_text(json.dumps({"kino_dir": str(kino)}), encoding="utf-8")
    monkeypatch.setenv(haglio_settings.SETTINGS_ENV, str(settings))
    return kino


@pytest.fixture
def media_root(tmp_path: Path) -> Path:
    return tmp_path / "videos" / "2D" / "AI"


def _upscaled(kino: Path, name: str) -> Path:
    video = kino / "2D" / "AI" / "portrait" / "provider" / name
    video.parent.mkdir(parents=True, exist_ok=True)
    video.write_bytes(b"")
    return video


def _original(media_root: Path, name: str) -> Path:
    video = media_root / "1_sorted" / "provider" / "portrait" / name
    video.parent.mkdir(parents=True, exist_ok=True)
    video.write_bytes(b"")
    return video


def test_finds_the_pre_upscale_original(kino, media_root):
    upscaled = _upscaled(kino, "abc_topaz.mp4")
    original = _original(media_root, "abc.mp4")

    assert original_rendition(str(upscaled), media_root) == str(original)


def test_finds_an_original_that_was_never_upscale_suffixed(kino, media_root):
    upscaled = _upscaled(kino, "abc.mp4")
    original = _original(media_root, "abc.mp4")

    assert original_rendition(str(upscaled), media_root) == str(original)


def test_no_original_on_disk(kino, media_root):
    upscaled = _upscaled(kino, "abc_topaz.mp4")

    assert original_rendition(str(upscaled), media_root) == ""


def test_video_outside_kinos_upscales(kino, media_root):
    stray = _original(media_root, "abc.mp4")

    assert original_rendition(str(stray), media_root) == ""


def test_a_video_in_kinos_trash_has_no_original(kino, media_root):
    trashed = kino / "trash" / "portrait" / "provider" / "abc_topaz.mp4"
    trashed.parent.mkdir(parents=True)
    trashed.write_bytes(b"")
    _original(media_root, "abc.mp4")

    assert original_rendition(str(trashed), media_root) == ""


def test_video_outside_the_library(kino, media_root):
    assert original_rendition(r"C:\elsewhere\abc_topaz.mp4", media_root) == ""


def test_no_media_root_configured(kino):
    upscaled = _upscaled(kino, "abc_topaz.mp4")

    assert original_rendition(str(upscaled), None) == ""


def test_no_video_path(kino, media_root):
    assert original_rendition("", media_root) == ""


class TestTheVersionsAClipCanBeSwitchedBetween:
    def test_the_video_leads_its_own_family(self, kino, media_root):
        upscaled = _upscaled(kino, "abc_topaz.mp4")
        original = _original(media_root, "abc.mp4")

        assert renditions(str(upscaled), media_root) == [str(upscaled), str(original)]

    def test_a_video_whose_original_is_gone_has_no_family(self, kino, media_root):
        upscaled = _upscaled(kino, "abc_topaz.mp4")

        assert renditions(str(upscaled), media_root) == []

    def test_a_video_outside_kinos_upscales_has_no_family(self, kino, media_root):
        stray = _original(media_root, "abc.mp4")

        assert renditions(str(stray), media_root) == []


def test_an_upscale_still_in_the_retired_2_outbox_finds_its_original_until_evolver_moves_it(kino, media_root):
    upscaled = media_root / "2_outbox" / "upscaled_by_orientation" / "portrait" / "provider" / "abc_topaz.mp4"
    upscaled.parent.mkdir(parents=True)
    upscaled.write_bytes(b"")
    original = _original(media_root, "abc.mp4")

    assert original_rendition(str(upscaled), media_root) == str(original)

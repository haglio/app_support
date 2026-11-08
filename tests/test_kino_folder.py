from __future__ import annotations

import json
from pathlib import Path

from app_support import haglio_settings, kino_folder


def test_kinos_folder_is_the_one_the_haglio_settings_name(tmp_path, monkeypatch):
    settings = tmp_path / "settings.json"
    settings.write_text(json.dumps({"kino_dir": "L:/library/videos/videos/kino"}), encoding="utf-8")
    monkeypatch.setenv(haglio_settings.SETTINGS_ENV, str(settings))

    assert kino_folder.kino_dir() == Path("L:/library/videos/videos/kino")


def test_the_upscales_sit_under_2d_ai_as_genaus_flicks_do():
    assert kino_folder.upscales_in(Path("C:/videos/kino")) == Path("C:/videos/kino/2D/AI")


def test_an_upscale_is_filed_by_orientation_then_source():
    assert kino_folder.upscale_in(Path("C:/videos/kino"), "portrait", "provider", "video one") == \
        Path("C:/videos/kino/2D/AI/portrait/provider/video one_topaz.mp4")


def test_kinos_trash_is_in_kinos_folder_as_genaus_is_in_genaus():
    assert kino_folder.trash_folder_in(Path("C:/videos/kino")) == Path("C:/videos/kino/trash")

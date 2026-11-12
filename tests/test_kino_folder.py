from __future__ import annotations

import json
from pathlib import Path, PurePosixPath

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



def test_an_ai_video_is_one_under_a_2d_ai_folder_whatever_shelf_it_is_on():
    assert [kino_folder.is_ai_video(PurePosixPath(place)) for place in (
        "kino/2D/AI/portrait/a-site/scene one_topaz.mp4",
        "genau/loops/2D/AI/portrait/scene one.mp4",
        "genau/loops/2D/non_AI/portrait/scene one.mp4",
        "genau/loops/VR/scene one.mp4",
        "kino/VR/scene one.mp4",
        "kino/2D/scene AI.mp4",
        "kino/AI/2D/scene one.mp4",
    )] == [True, True, False, False, False, False, False]


def test_the_upscales_kino_holds_are_on_its_ai_folder():
    assert kino_folder.is_ai_video(kino_folder.upscales_in(Path("kino")) / "portrait" / "c1.mp4")

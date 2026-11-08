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


LIBRARY = Path("L:/library")
KINO = LIBRARY / "videos" / "videos" / "kino"
RETIRED = LIBRARY / "videos" / "videos" / "2D" / "AI" / "2_outbox"


def test_an_upscale_filed_in_the_retired_2_outbox_went_to_kinos_folder():
    assert kino_folder.where_it_went(
        RETIRED / "upscaled_by_orientation" / "portrait" / "provider" / "video one_topaz.mp4",
        LIBRARY, KINO) == KINO / "2D" / "AI" / "portrait" / "provider" / "video one_topaz.mp4"


def test_a_video_in_the_retired_trash_went_to_kinos_trash():
    assert kino_folder.where_it_went(RETIRED / "trash" / "video one_topaz.mp4", LIBRARY, KINO) == (
        KINO / "trash" / "video one_topaz.mp4")


def test_anything_else_went_nowhere():
    for elsewhere in (LIBRARY / "videos" / "videos" / "2D" / "AI" / "1_sorted" / "a.mp4",
                      RETIRED / "stray.txt", Path("C:/elsewhere/a.mp4")):
        assert kino_folder.where_it_went(elsewhere, LIBRARY, KINO) is None

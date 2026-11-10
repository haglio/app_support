from pathlib import Path

from app_support.trash_names import name_before_trash, spot_in_trash


def test_a_video_whose_name_the_trash_does_not_hold_keeps_it(tmp_path: Path):
    assert spot_in_trash(tmp_path, "clip.mp4") == tmp_path / "clip.mp4"


def test_a_video_whose_name_the_trash_holds_takes_the_next_numbered_name(tmp_path: Path):
    (tmp_path / "clip.mp4").touch()
    (tmp_path / "clip__dup1.mp4").touch()

    assert spot_in_trash(tmp_path, "clip.mp4") == tmp_path / "clip__dup2.mp4"


def test_a_numbered_name_gives_back_the_name_the_video_had():
    assert name_before_trash("scene two_topaz__dup12.mp4") == "scene two_topaz.mp4"


def test_a_name_the_trash_never_numbered_is_the_name_it_had():
    assert name_before_trash("dup1 clip.mp4") == "dup1 clip.mp4"

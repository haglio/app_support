from __future__ import annotations

import json

from app_support import haglio_settings
from app_support.wrong_actions import origenerators_state, say, take


def test_a_video_said_to_have_the_wrong_actions_is_taken_once(tmp_path):
    say(tmp_path, "C:/library/video one.mp4")

    assert take(tmp_path) == ("C:/library/video one.mp4",)
    assert take(tmp_path) == ()


def test_videos_are_taken_in_the_order_they_were_said(tmp_path):
    for video in ("C:/library/video two.mp4", "C:/library/video one.mp4"):
        say(tmp_path, video)

    assert take(tmp_path) == ("C:/library/video two.mp4", "C:/library/video one.mp4")


def test_a_video_said_twice_before_it_is_taken_is_taken_once(tmp_path):
    say(tmp_path, "C:/library/video one.mp4")
    say(tmp_path, "C:/library/video one.mp4")

    assert take(tmp_path) == ("C:/library/video one.mp4",)


def test_nothing_said_takes_nothing_and_writes_nothing(tmp_path):
    assert take(tmp_path) == ()
    assert list(tmp_path.iterdir()) == []


def test_a_damaged_file_takes_nothing_and_the_next_say_starts_it_over(tmp_path):
    (tmp_path / "wrong_actions.json").write_text("not json", encoding="utf-8")

    assert take(tmp_path) == ()
    say(tmp_path, "C:/library/video one.mp4")
    assert take(tmp_path) == ("C:/library/video one.mp4",)


def test_they_are_said_in_the_state_of_the_origenerator_checkout_the_settings_name(
        tmp_path, monkeypatch):
    settings = tmp_path / "settings.json"
    settings.write_text(json.dumps({"project_roots": [str(tmp_path / "projects")],
                                    "library_root": str(tmp_path / "library")}),
                        encoding="utf-8")
    (tmp_path / "projects" / "origenerator").mkdir(parents=True)
    monkeypatch.setenv(haglio_settings.SETTINGS_ENV, str(settings))

    assert origenerators_state() == tmp_path / "projects" / "origenerator" / "state"

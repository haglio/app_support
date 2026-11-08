from __future__ import annotations

import json

from app_support import haglio_settings
from app_support.video_ids import (
    carried_forward,
    id_of,
    named_by_id,
    record_of,
    reference_to,
    video_named_by,
    videos_by_id,
)


def _record(path):
    return json.loads(path.read_text(encoding="utf-8"))


def _write(path, record):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record), encoding="utf-8")


def test_a_video_is_given_an_id_the_first_time_one_is_asked_for_and_the_same_one_after(tmp_path):
    record = tmp_path / "metadata" / "2D" / "scene one.json"
    _write(record, {"video": {"action": "alpha"}})

    given = id_of(record)

    assert given
    assert id_of(record) == given
    assert _record(record) == {"video": {"action": "alpha"}, "id": given}


def test_no_two_videos_are_given_the_same_id(tmp_path):
    assert id_of(tmp_path / "scene one.json") != id_of(tmp_path / "scene two.json")


def test_a_record_written_over_keeps_the_id_it_had(tmp_path):
    record = tmp_path / "scene one.json"
    given = id_of(record)

    assert carried_forward(_record(record), {"video": {"action": "beta"}}) == {
        "video": {"action": "beta"}, "id": given}
    assert carried_forward({}, {"video": {}}) == {"video": {}}


def test_each_id_is_found_at_the_video_its_record_mirrors_in_any_of_the_trees_asked(tmp_path):
    records, library, headset = tmp_path / "metadata", tmp_path / "videos", tmp_path / "vr drive"
    scene = library / "2D" / "scene one.mp4"
    far = headset / "far scene.mkv"
    for video in (scene, far):
        video.parent.mkdir(parents=True, exist_ok=True)
        video.write_bytes(b"")
    scene_id = id_of(records / "2D" / "scene one.json")
    far_id = id_of(records / "VR" / "far scene.json")
    id_of(records / "2D" / "gone.json")
    _write(records / "2D" / "never asked.json", {"video": {}})

    found = videos_by_id(((records, (library,)), (records / "VR", (headset,))))

    assert found == {scene_id: scene, far_id: far}


def _library(tmp_path, monkeypatch):
    settings = tmp_path / "settings.json"
    settings.write_text(json.dumps({"library_root": str(tmp_path / "library")}), encoding="utf-8")
    monkeypatch.setenv(haglio_settings.SETTINGS_ENV, str(settings))
    return tmp_path / "library"


def _video_in(library, name="scene one.mp4"):
    video = library / "videos" / "videos" / "2D" / name
    video.parent.mkdir(parents=True, exist_ok=True)
    video.write_bytes(b"")
    return video


def test_a_library_video_is_named_by_its_id_and_found_by_it_wherever_it_has_moved(
    tmp_path, monkeypatch,
):
    library = _library(tmp_path, monkeypatch)
    video = _video_in(library)

    reference = reference_to(video)
    moved = library / "videos" / "videos" / "elsewhere" / "scene one.mp4"
    for was, now in ((record_of(video), record_of(moved)), (video, moved)):
        now.parent.mkdir(parents=True, exist_ok=True)
        was.replace(now)

    assert reference == {"video_id": id_of(record_of(moved))}
    assert video_named_by(reference) == str(moved)


def test_a_video_outside_the_library_is_named_by_its_path(tmp_path, monkeypatch):
    _library(tmp_path, monkeypatch)
    outside = tmp_path / "downloads" / "scene one.mp4"

    assert reference_to(outside) == {"video_path": str(outside)}
    assert video_named_by({"video_path": str(outside)}) == str(outside)
    assert video_named_by({"video_id": "no such id"}) is None
    assert video_named_by({}) is None


def test_a_saved_reference_by_path_to_a_library_video_is_moved_to_its_id_once(
    tmp_path, monkeypatch,
):
    video = _video_in(_library(tmp_path, monkeypatch))
    outside = tmp_path / "downloads" / "scene one.mp4"

    moved = named_by_id({"session_name": "demo", "video_path": str(video)})

    assert moved == {"session_name": "demo", "video_id": id_of(record_of(video))}
    assert named_by_id(moved) is None
    assert named_by_id({"video_path": str(outside)}) is None
    assert named_by_id({"session_name": "demo"}) is None


def test_without_trees_named_the_ids_are_looked_up_in_the_library_the_haglio_settings_name(
    tmp_path, monkeypatch,
):
    settings = tmp_path / "settings.json"
    settings.write_text(json.dumps({"library_root": str(tmp_path / "library")}), encoding="utf-8")
    monkeypatch.setenv(haglio_settings.SETTINGS_ENV, str(settings))
    scene = tmp_path / "library" / "videos" / "videos" / "2D" / "scene one.mp4"
    scene.parent.mkdir(parents=True)
    scene.write_bytes(b"")

    record = record_of(scene)
    given = id_of(record)

    assert record == tmp_path / "library" / "videos" / "metadata" / "2D" / "scene one.json"
    assert videos_by_id() == {given: scene}
    assert record_of(tmp_path / "elsewhere" / "scene one.mp4") is None

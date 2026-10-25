"""A favorite is a mark on the video's own record, and the page it opens with it."""
from __future__ import annotations

import json

import pytest

from app_support.favorites import Favorite, favorites_under, is_favorite, mark, page_of


def _record(path):
    return json.loads(path.read_text(encoding="utf-8"))


def test_marking_a_video_a_favorite_writes_the_mark_on_a_record_it_did_not_have(tmp_path):
    record = tmp_path / "metadata" / "2D" / "scene one.json"

    assert mark(record, True) is True
    assert is_favorite(_record(record))


def test_clearing_a_favorite_takes_the_mark_off_and_leaves_the_rest_of_the_record(tmp_path):
    record = tmp_path / "scene one.json"
    record.write_text(json.dumps({"favorite": True, "video": {"action": "alpha"}}), encoding="utf-8")

    assert mark(record, False) is True
    assert _record(record) == {"video": {"action": "alpha"}}


def test_clearing_a_video_that_has_no_record_writes_none_and_no_folder_for_one(tmp_path):
    assert mark(tmp_path / "metadata" / "2D" / "scene two.json", False) is False
    assert not (tmp_path / "metadata").exists()


def test_the_page_a_favorite_opens_comes_with_its_mark_and_goes_with_it(tmp_path):
    record = tmp_path / "scene one.json"

    mark(record, True, page="https://example.com/gallery/101")
    assert page_of(_record(record)) == "https://example.com/gallery/101"

    mark(record, False)
    assert _record(record) == {}


def test_a_mark_given_no_page_keeps_the_page_the_favorite_already_had(tmp_path):
    record = tmp_path / "scene one.json"
    mark(record, True, page="https://example.com/gallery/101")

    assert mark(record, True) is False
    assert page_of(_record(record)) == "https://example.com/gallery/101"


def test_a_record_that_will_not_parse_is_somebody_elses_and_is_left_as_it_is(tmp_path):
    record = tmp_path / "scene one.json"
    record.write_text('{"video": {"action"', encoding="utf-8")

    assert mark(record, True) is False
    assert record.read_text(encoding="utf-8") == '{"video": {"action"'


@pytest.mark.parametrize("said", ["yes", 1, None, {}], ids=["text", "number", "null", "object"])
def test_only_a_mark_of_true_says_a_video_is_a_favorite(said):
    assert not is_favorite({"favorite": said})


def _video(library, name):
    video = library / name
    video.parent.mkdir(parents=True, exist_ok=True)
    video.write_bytes(b"")
    return video


def test_the_favorites_under_a_tree_of_records_are_the_videos_they_mark_with_their_pages(tmp_path):
    library, records = tmp_path / "videos" / "videos", tmp_path / "videos" / "metadata"
    loved = _video(library, "2D/scene one.mp4")
    _video(library, "2D/scene two.mp4")
    mark(records / "2D" / "scene one.json", True, page="https://example.com/gallery/101")
    (records / "2D" / "scene two.json").write_text(json.dumps({"video": {}}), encoding="utf-8")

    assert favorites_under(records, video_roots=(library,), video_suffixes=(".mp4",)) == [
        Favorite(video=loved, page="https://example.com/gallery/101")]


def test_a_favorite_whose_video_is_gone_is_no_favorite_of_the_library(tmp_path):
    library, records = tmp_path / "videos" / "videos", tmp_path / "videos" / "metadata"
    mark(records / "scene three.json", True)

    assert favorites_under(records, video_roots=(library,), video_suffixes=(".mp4",)) == []


def test_a_record_that_will_not_parse_marks_no_favorite_and_leaves_the_others_listed(tmp_path):
    library, records = tmp_path / "videos" / "videos", tmp_path / "videos" / "metadata"
    loved = _video(library, "scene one.mp4")
    _video(library, "scene two.mp4")
    mark(records / "scene one.json", True)
    (records / "scene two.json").write_text('{"favorite": tr', encoding="utf-8")

    assert favorites_under(records, video_roots=(library,), video_suffixes=(".mp4",)) == [
        Favorite(video=loved, page="")]

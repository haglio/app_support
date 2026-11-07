from __future__ import annotations

import json
from pathlib import Path

from app_support.mirrored_tree import (
    filed_record,
    library_roots_beside,
    mirrored_path,
    mirrored_source,
    record_path,
)


def test_a_record_sits_at_the_same_relative_place_under_the_other_root(tmp_path: Path):
    library = tmp_path / "videos" / "videos"
    records = tmp_path / "videos" / "metadata"

    assert mirrored_path(
        library / "2D" / "outbox" / "clip.mp4",
        roots=(library,),
        mirror_root=records,
        suffix=".json",
    ) == records / "2D" / "outbox" / "clip.json"


def test_a_file_under_no_root_has_no_record_as_a_video_parked_outside_the_library_wants_none(tmp_path: Path):
    assert mirrored_path(
        tmp_path / "elsewhere" / "clip.mp4",
        roots=(tmp_path / "videos" / "videos",),
        mirror_root=tmp_path / "videos" / "metadata",
        suffix=".json",
    ) is None


def test_the_first_root_that_holds_the_file_is_the_one_it_is_measured_from_so_the_narrower_goes_first(
        tmp_path: Path):
    library = tmp_path / "videos" / "videos"
    wider = tmp_path / "videos"
    records = tmp_path / "videos" / "metadata"

    assert mirrored_path(
        library / "clip.mp4",
        roots=(library, wider),
        mirror_root=records,
        suffix=".json",
    ) == records / "clip.json"


def test_a_file_beside_the_tree_is_measured_from_the_root_that_holds_both(tmp_path: Path):
    library = tmp_path / "videos" / "videos"
    wider = tmp_path / "videos"
    records = tmp_path / "videos" / "metadata"

    assert mirrored_path(
        wider / "delivered" / "clips" / "loop.mp4",
        roots=(library, wider),
        mirror_root=records,
        suffix=".json",
    ) == records / "delivered" / "clips" / "loop.json"


def test_a_root_spelled_in_another_case_still_holds_its_files(tmp_path: Path):
    library = tmp_path / "videos" / "videos"
    records = tmp_path / "videos" / "metadata"
    shouted = Path(str(library).upper())

    assert mirrored_path(
        library / "clip.mp4", roots=(shouted,), mirror_root=records, suffix=".json"
    ) == records / "clip.json"


def test_the_suffix_is_the_callers_since_not_every_mirrored_tree_holds_records(
    tmp_path: Path,
):
    library = tmp_path / "videos" / "videos"

    assert mirrored_path(
        library / "clip.mp4",
        roots=(library,),
        mirror_root=tmp_path / "videos" / "scripts",
        suffix=".funscript",
    ) == tmp_path / "videos" / "scripts" / "clip.funscript"


def test_a_caller_given_only_the_mirror_root_gets_the_pair_it_sits_beside(tmp_path: Path):
    records = tmp_path / "videos" / "metadata"

    assert library_roots_beside(records) == (
        tmp_path / "videos" / "videos",
        tmp_path / "videos",
    )


def test_a_record_leads_back_to_the_file_it_mirrors_whatever_that_files_suffix(tmp_path: Path):
    library = tmp_path / "videos" / "videos"
    records = tmp_path / "videos" / "metadata"
    video = library / "2D" / "outbox" / "scene one.webm"
    video.parent.mkdir(parents=True)
    video.write_bytes(b"")

    assert mirrored_source(
        records / "2D" / "outbox" / "scene one.json",
        roots=(library, tmp_path / "videos"),
        mirror_root=records,
        suffixes=(".mp4", ".webm"),
    ) == video


def test_a_record_whose_file_is_gone_leads_nowhere(tmp_path: Path):
    records = tmp_path / "videos" / "metadata"

    assert mirrored_source(
        records / "scene two.json",
        roots=(tmp_path / "videos" / "videos",),
        mirror_root=records,
        suffixes=(".mp4",),
    ) is None


def test_a_videos_record_is_found_from_the_library_beside_the_records(tmp_path: Path):
    records = tmp_path / "videos" / "metadata"

    assert record_path(tmp_path / "videos" / "videos" / "portrait" / "scene one.mp4",
                       records) == records / "portrait" / "scene one.json"
    assert record_path(tmp_path / "elsewhere" / "scene one.mp4", records) is None


def test_a_video_kept_in_a_library_elsewhere_has_its_record_measured_from_that_library(
        tmp_path: Path):
    records = tmp_path / "videos" / "metadata"
    elsewhere = tmp_path / "another drive" / "videos"

    assert record_path(elsewhere / "VR" / "scene two.mp4", records,
                       more_roots=(elsewhere,)) == records / "VR" / "scene two.json"


def _records_library(tmp_path):
    return tmp_path / "videos" / "videos", tmp_path / "videos" / "metadata"


def test_a_videos_record_is_the_one_filed_for_it(tmp_path):
    videos, records = _records_library(tmp_path)
    record = records / "portrait" / "scene one.json"
    record.parent.mkdir(parents=True)
    record.write_text(json.dumps({"watch": {"weight": 4.0}}), encoding="utf-8")

    assert filed_record(videos / "portrait" / "scene one.mp4", records) == {"watch": {"weight": 4.0}}


def test_a_video_with_no_record_or_a_broken_one_or_outside_the_library_has_an_empty_one(tmp_path):
    videos, records = _records_library(tmp_path)
    broken = records / "portrait" / "scene two.json"
    broken.parent.mkdir(parents=True)
    broken.write_text('{"watch": {"weight"', encoding="utf-8")

    assert filed_record(videos / "portrait" / "scene one.mp4", records) == {}
    assert filed_record(videos / "portrait" / "scene two.mp4", records) == {}
    assert filed_record(tmp_path / "elsewhere" / "scene one.mp4", records) == {}
    assert filed_record(videos / "portrait" / "scene one.mp4", None) == {}

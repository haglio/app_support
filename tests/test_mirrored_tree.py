"""The one rule pairing a tree of records with the tree of files it describes."""
from __future__ import annotations

from pathlib import Path

from app_support.mirrored_tree import library_roots_beside, mirrored_path


def test_a_record_sits_at_the_same_relative_place_under_the_other_root(tmp_path: Path):
    library = tmp_path / "videos" / "videos"
    records = tmp_path / "videos" / "metadata"

    assert mirrored_path(
        library / "2D" / "outbox" / "clip.mp4",
        roots=(library,),
        mirror_root=records,
        suffix=".json",
    ) == records / "2D" / "outbox" / "clip.json"


def test_a_file_under_no_root_has_no_record(tmp_path: Path):
    assert mirrored_path(
        tmp_path / "elsewhere" / "clip.mp4",
        roots=(tmp_path / "videos" / "videos",),
        mirror_root=tmp_path / "videos" / "metadata",
        suffix=".json",
    ) is None


def test_the_first_root_that_holds_the_file_is_the_one_it_is_measured_from(tmp_path: Path):
    """The roots are tried in order and the narrower one comes first, because a
    file inside it is inside the wider one too -- measured from the wider one
    its record would land a folder deep in the mirror, under the narrow root's
    own name."""
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
    """Clips delivered to a folder of their own sit beside the library rather
    than in it, and their records are filed the same way -- from the folder that
    holds both, so the delivered folder's name is part of the record's path."""
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
    """The library lives on a disk that does not distinguish them, so a root
    configured with a capital in it is the same place -- which
    ``relative_to`` alone does not know, and a whole report came back empty
    because of it."""
    library = tmp_path / "videos" / "videos"
    records = tmp_path / "videos" / "metadata"
    shouted = Path(str(library).upper())

    assert mirrored_path(
        library / "clip.mp4", roots=(shouted,), mirror_root=records, suffix=".json"
    ) == records / "clip.json"


def test_the_suffix_is_the_callers_since_not_every_mirrored_tree_holds_records(
    tmp_path: Path,
):
    """The scripts a video is driven by mirror it the same way its records do."""
    library = tmp_path / "videos" / "videos"

    assert mirrored_path(
        library / "clip.mp4",
        roots=(library,),
        mirror_root=tmp_path / "videos" / "scripts",
        suffix=".funscript",
    ) == tmp_path / "videos" / "scripts" / "clip.funscript"


def test_a_caller_given_only_the_mirror_root_gets_the_pair_it_sits_beside(tmp_path: Path):
    """Two apps are configured with the record tree and nothing else, and each
    had worked the library out from it by hand.  The layout is the same one both
    assumed, said once: the library beside the mirror under one parent, and that
    parent second, for whatever sits beside the library."""
    records = tmp_path / "videos" / "metadata"

    assert library_roots_beside(records) == (
        tmp_path / "videos" / "videos",
        tmp_path / "videos",
    )

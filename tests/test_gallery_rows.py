from __future__ import annotations

import json
import sqlite3

import pytest

from app_support import gallery_rows


def _gallery_with_columns(root, column: str, values: list[tuple]):
    db_path = root / "gallery.db"
    connection = sqlite3.connect(db_path)
    connection.execute(f"CREATE TABLE generations ({column} TEXT)")
    connection.executemany("INSERT INTO generations VALUES (?)", values)
    connection.commit()
    connection.close()
    return db_path


def test_a_missing_gallery_is_named_in_the_error(tmp_path):
    with pytest.raises(FileNotFoundError) as raised:
        gallery_rows.rows(("output_files",), db_path=tmp_path / "gallery.db")

    assert "gallery.db" in str(raised.value)
    assert not (tmp_path / "gallery.db").exists()


def test_a_column_an_older_gallery_lacks_is_missing_from_every_row(tmp_path):
    db_path = _gallery_with_columns(tmp_path, "output_files", [('[{"filename": "a.mp4"}]',)])

    found = gallery_rows.rows(("output_files",), optional=("remade_at",), db_path=db_path)

    assert found == [{"output_files": '[{"filename": "a.mp4"}]'}]


def test_the_gallery_is_opened_so_nothing_here_can_write_to_it(tmp_path):
    db_path = _gallery_with_columns(tmp_path, "output_files", [("[]",)])
    connection = gallery_rows.connect_read_only(db_path)
    try:
        with pytest.raises(sqlite3.OperationalError):
            connection.execute("DELETE FROM generations")
    finally:
        connection.close()


def test_the_file_names_are_the_ones_the_row_lists():
    row = {"output_files": json.dumps([{"filename": "a.mp4"}, {"filename": "b.png"}])}

    assert gallery_rows.output_names(row) == ["a.mp4", "b.png"]


def test_a_row_whose_list_cannot_be_read_costs_that_row_and_not_the_run():
    assert gallery_rows.output_names({"output_files": "{not json"}) == []
    assert gallery_rows.output_names({"output_files": '"text"'}) == []
    assert gallery_rows.output_entries({"output_files": "{not json"}) is None


def test_a_video_is_told_by_its_extension_whatever_its_case():
    assert [gallery_rows.is_video_name(name) for name in ("a.mp4", "B.MKV", "c.png")] == [
        True, True, False]


def _made_here(prompt_id: str, *filenames: str, **columns) -> dict:
    return {"prompt_id": prompt_id,
            "output_files": json.dumps([{"filename": name, "subfolder": "video"}
                                        for name in filenames]), **columns}


@pytest.mark.parametrize("filed_as", [
    "alpha_00007_.mp4", "alpha_00007_-audio.mp4", "alpha_00007__topaz.mp4",
    "alpha_00007_-audio_topaz.mp4", "alpha_00007_-audio_topaz (2).mp4",
    "alpha_00007_ (3)_topaz_cfr.mp4", "alpha_00007_-audio_apo8_iris2.mp4", "ALPHA_00007_-AUDIO.MP4",
])
def test_a_copy_the_library_made_of_a_video_finds_the_row_that_made_it(tmp_path, filed_as):
    rows = gallery_rows.VideoRows([_made_here("gen-1", "alpha_00007_.mp4"),
                                   _made_here("gen-2", "beta_00007_.mp4")])

    assert rows(tmp_path / "kino" / filed_as) == "gen-1"


def test_a_row_whose_kept_copy_is_the_one_with_sound_is_found_by_the_name_without_it(tmp_path):
    rows = gallery_rows.VideoRows([_made_here("gen-1", "alpha_00007_-audio.mp4")])

    assert rows(tmp_path / "kino" / "alpha_00007__topaz.mp4") == "gen-1"


def test_a_name_no_row_was_made_with_finds_none(tmp_path):
    rows = gallery_rows.VideoRows([_made_here("gen-1", "alpha_00007_.mp4")])

    assert rows(tmp_path / "alpha_00008_.mp4") is None


def test_a_video_brought_in_from_outside_is_found_at_the_place_its_row_keeps_it(tmp_path):
    kept = tmp_path / "kino" / "scene one.mp4"
    rows = gallery_rows.VideoRows([
        {"prompt_id": "outside-1", "output_files": json.dumps(
            [{"filename": "other name.mp4", "library_path": str(kept)}, "not a file entry"])}])

    assert rows(str(kept).upper()) == "outside-1"


def test_an_upscale_evolver_made_is_found_at_the_place_its_row_names(tmp_path):
    upscale = tmp_path / "kino" / "made up name.mp4"
    rows = gallery_rows.VideoRows([_made_here("gen-1", "alpha_00007_.mp4",
                                              evolver_upscale=str(upscale))])

    assert rows(upscale) == "gen-1"


def test_the_first_row_that_made_a_name_is_the_one_found(tmp_path):
    rows = gallery_rows.VideoRows([_made_here("gen-1", "alpha_00007_.mp4"),
                                   _made_here("gen-2", "alpha_00007_.mp4")])

    assert rows(tmp_path / "alpha_00007_.mp4") == "gen-1"



@pytest.mark.parametrize(("source", "here"), [
    (None, True), ("", True), (gallery_rows.GENERATED, True), ("experiment", True),
    (gallery_rows.OUTSIDE, False), (gallery_rows.STARTING_FRAME, False),
    (gallery_rows.LEFT_OUT, False),
])
def test_a_row_with_no_source_was_made_here_and_one_brought_in_was_not(source, here):
    assert gallery_rows.made_here({"prompt_id": "made-up", "source": source}) is here


def test_the_sources_are_the_words_the_database_stores():
    assert (gallery_rows.GENERATED, gallery_rows.OUTSIDE, gallery_rows.STARTING_FRAME,
            gallery_rows.LEFT_OUT) == ("generated", "outside", "starting_frame", "left_out")

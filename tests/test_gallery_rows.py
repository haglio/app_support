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

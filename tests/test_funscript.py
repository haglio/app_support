from __future__ import annotations

import json
from pathlib import Path

from app_support.funscript import (
    actions_of,
    document,
    read,
    read_actions,
    write,
)


def test_a_document_that_lists_no_actions_has_no_actions():
    assert actions_of({"version": "1.0"}) == []


def test_a_document_whose_actions_are_not_a_list_has_no_actions():
    assert actions_of({"actions": {"at": 0, "pos": 40}}) == []


def test_a_document_lists_the_actions_it_lists():
    actions = [{"at": 0, "pos": 0}, {"at": 500, "pos": 90}]

    assert actions_of({"actions": actions}) == actions


def test_a_script_that_is_not_there_reads_as_a_document_with_no_actions(tmp_path: Path):
    assert read(tmp_path / "absent.funscript") == {}
    assert read_actions(tmp_path / "absent.funscript") == []


def test_no_path_at_all_reads_as_no_actions():
    assert read_actions(None) == []


def test_a_script_that_will_not_parse_reads_as_no_actions_and_says_so(tmp_path, caplog):
    path = tmp_path / "torn.funscript"
    path.write_text('{"actions": [{"at": 0,', encoding="utf-8")

    assert read_actions(path) == []

    assert "torn.funscript" in caplog.text


def test_a_document_that_is_not_an_object_reads_as_no_actions(tmp_path: Path):
    path = tmp_path / "list.funscript"
    path.write_text("[1, 2, 3]", encoding="utf-8")

    assert read_actions(path) == []


def test_a_built_document_carries_every_key_an_external_player_reads():
    built = document([], duration_seconds=100, creator="Example Editor")

    assert built == {
        "actions": [],
        "inverted": False,
        "metadata": {
            "bookmarks": [],
            "chapters": [],
            "creator": "Example Editor",
            "description": "",
            "duration": 100,
            "license": "",
            "notes": "",
            "performers": [],
            "script_url": "",
            "tags": [],
            "title": "",
            "type": "basic",
            "video_url": "",
        },
        "range": 100,
        "version": "1.0",
    }


def test_a_built_document_puts_its_actions_in_time_order():
    built = document(
        [{"at": 900, "pos": 0}, {"at": 100, "pos": 80}], duration_seconds=2
    )

    assert [action["at"] for action in built["actions"]] == [100, 900]


def test_a_written_script_reads_back_as_the_document_that_was_written(tmp_path: Path):
    path = tmp_path / "scripts" / "clip.funscript"
    built = document([{"at": 0, "pos": 10}], duration_seconds=1, creator="Example Editor")

    write(path, built)

    assert read(path) == built


def test_a_script_read_while_it_is_being_replaced_reads_whole(tmp_path: Path, being_replaced):
    path = tmp_path / "clip.funscript"
    built = document([{"at": 0, "pos": 10}], duration_seconds=1)
    write(path, built)

    with being_replaced(path):
        assert read(path) == built


def test_a_script_is_written_the_way_the_players_that_read_one_write_it(tmp_path: Path):
    path = tmp_path / "clip.funscript"

    write(path, document([{"at": 0, "pos": 10}], duration_seconds=1))

    assert path.read_text(encoding="utf-8").count("\n") == 0


def test_a_script_lands_whole_or_not_at_all(tmp_path: Path):
    path = tmp_path / "clip.funscript"
    path.write_text(json.dumps({"actions": [{"at": 0, "pos": 1}]}), encoding="utf-8")

    write(path, document([{"at": 0, "pos": 99}], duration_seconds=1))

    assert list(path.parent.iterdir()) == [path]

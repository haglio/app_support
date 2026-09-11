"""The one statement of what a .funscript document is, and what it answers."""
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
    """The family's one answer, where it had three.

    A reader raised, a reader answered nothing, and a reader answered none, so
    "this script drives the device through nothing" arrived at three call sites
    as three different things to handle.  None is the answer, because it is the
    one every caller already does the same thing with.
    """
    assert actions_of({"version": "1.0"}) == []


def test_a_document_whose_actions_are_not_a_list_has_no_actions():
    assert actions_of({"actions": {"at": 0, "pos": 40}}) == []


def test_a_document_lists_the_actions_it_lists():
    actions = [{"at": 0, "pos": 0}, {"at": 500, "pos": 90}]

    assert actions_of({"actions": actions}) == actions


def test_a_script_that_is_not_there_reads_as_a_document_with_no_actions(tmp_path: Path):
    """Absent is ordinary: most videos have no script, and every caller of this
    asks before it knows."""
    assert read(tmp_path / "absent.funscript") == {}
    assert read_actions(tmp_path / "absent.funscript") == []


def test_no_path_at_all_reads_as_no_actions():
    """"Which script does this video have" answers None, and it is handed
    straight here rather than guarded at each call site."""
    assert read_actions(None) == []


def test_a_script_that_will_not_parse_reads_as_no_actions_and_says_so(tmp_path, caplog):
    """A torn or hand-edited file must not raise into a run loop -- but a script
    that is there and unreadable is a broken file, and swallowing it silently is
    how it stays broken."""
    path = tmp_path / "torn.funscript"
    path.write_text('{"actions": [{"at": 0,', encoding="utf-8")

    assert read_actions(path) == []

    assert "torn.funscript" in caplog.text


def test_a_document_that_is_not_an_object_reads_as_no_actions(tmp_path: Path):
    path = tmp_path / "list.funscript"
    path.write_text("[1, 2, 3]", encoding="utf-8")

    assert read_actions(path) == []


def test_a_built_document_carries_every_key_an_external_player_reads():
    """The metadata block is what a player outside this family reads off a
    script, so the shared builder keeps every key the repo that had it wrote --
    the empty ones included, since a player that reads a key and finds it
    missing is not the same as one that reads it and finds it empty."""
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


def test_a_script_is_written_the_way_the_players_that_read_one_write_it(tmp_path: Path):
    """Minified.  A script runs to thousands of actions, and every writer of one
    outside this family emits it on a single line."""
    path = tmp_path / "clip.funscript"

    write(path, document([{"at": 0, "pos": 10}], duration_seconds=1))

    assert path.read_text(encoding="utf-8").count("\n") == 0


def test_a_script_lands_whole_or_not_at_all(tmp_path: Path):
    """Three apps read these while a fourth rewrites them, so a reader must
    never catch one half-written."""
    path = tmp_path / "clip.funscript"
    path.write_text(json.dumps({"actions": [{"at": 0, "pos": 1}]}), encoding="utf-8")

    write(path, document([{"at": 0, "pos": 99}], duration_seconds=1))

    assert list(path.parent.iterdir()) == [path]

from __future__ import annotations

import json
from pathlib import Path

from app_support.funscript import (
    actions_of,
    document,
    generated_mark_of,
    generated_marks_tree_in,
    read,
    read_actions,
    script_of,
    scripts_tree_in,
    write,
)


def test_a_document_that_lists_no_actions_has_no_actions():
    assert actions_of({"version": "1.0"}) == []


def test_a_document_whose_actions_are_not_a_list_has_no_actions():
    assert actions_of({"actions": {"at": 0, "pos": 40}}) == []


def test_a_document_lists_the_actions_it_lists():
    actions = [{"at": 0, "pos": 0}, {"at": 500, "pos": 90}]

    assert actions_of({"actions": actions}) == actions


def test_a_script_that_is_not_there_reads_quietly_as_no_actions_most_videos_have_none(tmp_path: Path, caplog):
    assert read(tmp_path / "absent.funscript") == {}
    assert read_actions(tmp_path / "absent.funscript") == []
    assert caplog.text == ""


def test_no_path_at_all_reads_as_no_actions_the_answer_a_video_with_no_script_gives():
    assert read_actions(None) == []


def test_a_script_that_will_not_parse_reads_as_no_actions_and_says_so_never_raising_into_a_run_loop(tmp_path, caplog):
    path = tmp_path / "torn.funscript"
    path.write_text('{"actions": [{"at": 0,', encoding="utf-8")

    assert read_actions(path) == []

    assert "torn.funscript" in caplog.text


def test_a_document_that_is_not_an_object_reads_as_no_actions(tmp_path: Path):
    path = tmp_path / "list.funscript"
    path.write_text("[1, 2, 3]", encoding="utf-8")

    assert read_actions(path) == []


def test_a_built_document_carries_every_key_an_external_player_reads_with_the_videos_own_duration_since_a_script_can_stop_before_it():
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


def test_a_script_is_written_on_one_line_as_other_players_write_one_that_runs_to_thousands_of_actions(tmp_path: Path):
    path = tmp_path / "clip.funscript"

    write(path, document([{"at": 0, "pos": 10}], duration_seconds=1))

    assert path.read_text(encoding="utf-8").count("\n") == 0


def test_a_script_lands_whole_or_not_at_all(tmp_path: Path):
    path = tmp_path / "clip.funscript"
    path.write_text(json.dumps({"actions": [{"at": 0, "pos": 1}]}), encoding="utf-8")

    write(path, document([{"at": 0, "pos": 99}], duration_seconds=1))

    assert list(path.parent.iterdir()) == [path]


def test_a_videos_script_sits_in_the_scripts_tree_where_the_video_sits_in_the_library(tmp_path: Path):
    trees = tmp_path / "videos"
    video = trees / "videos" / "VR" / "finished" / "scene one.mp4"

    script = script_of(video, library=trees / "videos", scripts_tree=scripts_tree_in(trees))

    assert script == trees / "scripts" / "scripts" / "VR" / "finished" / "scene one.funscript"


def test_a_video_outside_the_library_has_no_script_in_its_scripts_tree(tmp_path: Path):
    trees = tmp_path / "videos"

    assert script_of(tmp_path / "elsewhere" / "clip.mp4", library=trees / "videos",
                     scripts_tree=scripts_tree_in(trees)) is None


def test_the_mark_saying_no_person_wrote_a_script_sits_where_the_script_sits_in_the_marks_tree(tmp_path: Path):
    trees = tmp_path / "videos"
    script = trees / "scripts" / "scripts" / "VR" / "scene one.funscript"

    mark = generated_mark_of(script, scripts_tree=scripts_tree_in(trees), marks_tree=generated_marks_tree_in(trees))

    assert mark == trees / "scripts" / "generated" / "VR" / "scene one.generated"


def test_a_script_outside_the_scripts_tree_has_no_mark(tmp_path: Path):
    trees = tmp_path / "videos"

    assert generated_mark_of(tmp_path / "elsewhere" / "clip.funscript", scripts_tree=scripts_tree_in(trees),
                             marks_tree=generated_marks_tree_in(trees)) is None

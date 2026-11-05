from __future__ import annotations

import json

from app_support.video_action import strike


def _record(path):
    return json.loads(path.read_text(encoding="utf-8"))


def test_striking_a_videos_act_takes_it_off_and_remembers_what_it_was(tmp_path):
    record = tmp_path / "scene one.json"
    record.write_text(json.dumps({"video": {"action": "Alpha", "prompt": "a made-up prompt"}}),
                      encoding="utf-8")

    assert strike(record) == "Alpha"

    assert _record(record) == {"video": {"wrong_action": "Alpha", "prompt": "a made-up prompt"}}


def test_a_record_with_no_act_is_left_as_it_is(tmp_path):
    record = tmp_path / "scene one.json"
    record.write_text(json.dumps({"video": {"prompt": "a made-up prompt"}}), encoding="utf-8")
    before = record.read_text(encoding="utf-8")

    assert strike(record) == ""

    assert record.read_text(encoding="utf-8") == before


def test_a_video_with_no_record_has_no_act_to_strike_and_gets_no_record(tmp_path):
    record = tmp_path / "metadata" / "portrait" / "scene two.json"

    assert strike(record) == ""

    assert not (tmp_path / "metadata").exists()


def test_a_record_that_is_no_document_is_somebody_elses_and_is_left_as_it_is(tmp_path):
    record = tmp_path / "scene one.json"
    record.write_text("[not a document]", encoding="utf-8")

    assert strike(record) == ""

    assert record.read_text(encoding="utf-8") == "[not a document]"

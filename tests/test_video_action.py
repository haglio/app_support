from __future__ import annotations

import json

from app_support.video_action import (
    actions_of,
    strike,
    with_actions,
)


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


def test_a_videos_actions_are_read_off_its_record_in_the_order_they_were_given():
    assert actions_of({"video": {"action": "Alpha", "labels": ["beta", "alpha"]}}) == ("beta", "alpha")


def test_a_record_naming_no_actions_has_none_and_its_site_action_is_none_of_them():
    assert [actions_of(record) for record in ({}, {"video": {"action": "Alpha"}}, {"video": "a note"},
                                              {"video": {"labels": "alpha"}})] == [(), (), (), ()]


def test_giving_a_record_actions_puts_them_beside_its_site_action():
    assert with_actions({"video": {"action": "Alpha"}}, ("alpha", "beta")) == {
        "video": {"action": "Alpha", "labels": ["alpha", "beta"]}}


def test_giving_a_record_the_actions_it_has_leaves_it_as_it_is():
    assert with_actions({"video": {"labels": ["alpha"]}}, ("alpha",)) is None


def test_giving_a_record_no_actions_takes_its_actions_off_and_keeps_its_site_action():
    assert with_actions({"video": {"action": "Alpha", "labels": ["alpha"]}}, ()) == {"video": {"action": "Alpha"}}


def test_giving_a_record_with_no_video_in_it_actions_gives_it_one():
    assert with_actions({}, ("alpha",)) == {"video": {"labels": ["alpha"]}}


def test_a_record_whose_video_is_no_document_is_somebody_elses_and_gets_no_actions():
    assert with_actions({"video": "a note"}, ("alpha",)) is None


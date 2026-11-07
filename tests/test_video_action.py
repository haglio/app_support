from __future__ import annotations

import json

from app_support.video_action import labeled, labels_of, strike


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


def test_a_videos_labels_are_read_off_its_record_in_the_order_they_were_given():
    assert labels_of({"video": {"action": "Alpha", "labels": ["beta", "alpha"]}}) == ("beta", "alpha")


def test_a_record_naming_no_labels_has_none():
    assert [labels_of(record) for record in ({}, {"video": {"action": "Alpha"}}, {"video": "a note"},
                                             {"video": {"labels": "alpha"}})] == [(), (), (), ()]


def test_labeling_a_record_puts_its_labels_beside_its_action():
    assert labeled({"video": {"action": "Alpha"}}, ("alpha", "beta")) == {
        "video": {"action": "Alpha", "labels": ["alpha", "beta"]}}


def test_labeling_a_record_with_the_labels_it_has_leaves_it_as_it_is():
    assert labeled({"video": {"labels": ["alpha"]}}, ("alpha",)) is None


def test_labeling_a_record_with_no_labels_takes_its_labels_off():
    assert labeled({"video": {"action": "Alpha", "labels": ["alpha"]}}, ()) == {"video": {"action": "Alpha"}}


def test_labeling_a_record_with_no_video_in_it_gives_it_one():
    assert labeled({}, ("alpha",)) == {"video": {"labels": ["alpha"]}}


def test_a_record_whose_video_is_no_document_is_somebody_elses_and_is_not_labeled():
    assert labeled({"video": "a note"}, ("alpha",)) is None

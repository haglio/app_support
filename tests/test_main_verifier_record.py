import json

from app_support.main_verifier_record import INCIDENTS_NAME, read_incidents, shipped_again


def test_the_incidents_are_read_in_order_past_a_line_cut_short(tmp_path):
    (tmp_path / INCIDENTS_NAME).write_text("\n".join([json.dumps({"kind": "flaky"}), '{"kind": "bro',
                                                      json.dumps({"kind": "broke main"})]), encoding="utf-8")

    assert read_incidents(tmp_path) == [{"kind": "flaky"}, {"kind": "broke main"}]


def test_no_record_yet_is_no_incidents(tmp_path):
    assert read_incidents(tmp_path) == []


def test_the_changes_shipped_again_are_those_the_verifier_recorded_as_shipped_again():
    assert shipped_again([{"pull_request": 41, "shipped_again_by": 79}, {"pull_request": 42},
                          {"pull_request": 43, "shipped_again_by": None}]) == {41}

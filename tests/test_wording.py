from __future__ import annotations

from app_support.wording import listed


def test_one_thing_reads_as_itself():
    assert listed(["the parts"]) == "the parts"


def test_two_things_read_with_and_between_them():
    assert listed(["the parts", "the levers"]) == "the parts and the levers"


def test_more_things_read_with_commas_and_and_before_the_last():
    assert listed(["the parts", "the levers", "the hinges"]) == "the parts, the levers and the hinges"

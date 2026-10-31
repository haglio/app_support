"""The four files an Origenerator opened on its own and a Fun Time session hand
each other: each one's writer against its reader, the process a line names, and
the state folders every copy of either app meets the others in.

Every pid and every checkout here is fabricated; the one live process the
tests name is the test run's own.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pytest

from app_support import origenerator_handoff as handoff
from app_support.win32 import process_started


def _this_process() -> str:
    return f"{os.getpid()} {process_started(os.getpid())}"


def _a_process_that_has_ended() -> str:
    return f"{os.getpid()} {process_started(os.getpid()) - 1}"


def _write(place: Path, name: str, text: str) -> None:
    place.mkdir(parents=True, exist_ok=True)
    (place / name).write_text(text, encoding="utf-8")


class TestTheProcessALineNames:
    def test_it_started_in_the_ticks_windows_counts_from_1601_as_every_release_wrote(self):
        ticks_a_second = 10_000_000
        seconds_from_1601_to_1970 = 11_644_473_600
        now = int((time.time() + seconds_from_1601_to_1970) * ticks_a_second)

        started = handoff.this_process().created_at

        assert 0 < now - started < 24 * 3600 * ticks_a_second

    def test_it_is_named_alike_every_time(self):
        assert handoff.this_process() == handoff.this_process()


class TestTheOffer:
    def test_a_copy_offers_itself_by_its_own_process(self):
        assert handoff.offer_of(handoff.this_process()) == _this_process()

    def test_a_copy_still_starting_says_so_in_its_offer(self):
        assert handoff.offer_of(handoff.this_process(), starting=True) == f"{_this_process()} starting"

    def test_a_copy_still_being_built_offers_itself_as_starting(self, tmp_path: Path):
        handoff.offer_this_process(tmp_path, starting=True)

        assert (tmp_path / handoff.OFFER).read_text(encoding="utf-8") == f"{_this_process()} starting"

    def test_a_preview_offers_itself_in_the_production_copy_s_state_too(self, tmp_path: Path):
        preview, production = tmp_path / "preview" / "state", tmp_path / "production" / "state"

        handoff.offer_this_process(preview, production, starting=True)

        assert [handoff.the_offer_in(place) for place in (preview, production)] == [
            handoff.Offer(handoff.this_process(), starting=True)] * 2

    def test_an_open_copy_is_the_process_its_offer_names(self, tmp_path: Path):
        _write(tmp_path, handoff.OFFER, _this_process())

        assert handoff.the_offer_in(tmp_path) == handoff.Offer(handoff.this_process(), starting=False)

    def test_a_copy_still_starting_is_read_as_starting(self, tmp_path: Path):
        _write(tmp_path, handoff.OFFER, f"{_this_process()} starting")

        assert handoff.the_offer_in(tmp_path) == handoff.Offer(handoff.this_process(), starting=True)

    @pytest.mark.parametrize("offer", ["", "1234", "1234 soon", "one two"])
    def test_an_offer_that_names_no_process_is_no_open_copy(self, tmp_path: Path, offer: str):
        _write(tmp_path, handoff.OFFER, offer)

        assert handoff.the_offer_in(tmp_path) is None

    def test_an_offer_left_by_a_process_that_has_ended_is_no_open_copy(self, tmp_path: Path):
        _write(tmp_path, handoff.OFFER, _a_process_that_has_ended())

        assert handoff.the_offer_in(tmp_path) is None

    def test_an_offer_with_a_word_this_release_does_not_know_is_no_open_copy(self, tmp_path: Path):
        _write(tmp_path, handoff.OFFER, f"{_this_process()} sleeping")

        assert handoff.the_offer_in(tmp_path) is None

    def test_no_offer_is_no_open_copy(self, tmp_path: Path):
        assert handoff.the_offer_in(tmp_path) is None

    def test_a_withdrawn_offer_takes_its_slideshow_mark_with_it_everywhere_it_stood(self, tmp_path: Path):
        places = (tmp_path / "preview", tmp_path / "production")
        for place in places:
            _write(place, handoff.OFFER, _this_process())
            _write(place, handoff.SHOWING, handoff.slideshow_mark_of(handoff.this_process(), "portrait"))

        handoff.withdraw_the_offer(*places)

        assert [sorted(path.name for path in place.iterdir()) for place in places] == [[], []]


class TestTheSlideshowMark:
    @pytest.mark.parametrize("shape", ["portrait", "landscape", "both"])
    def test_the_shape_an_open_copy_marks_is_the_shape_read(self, tmp_path: Path, shape: str):
        _write(tmp_path, handoff.SHOWING, handoff.slideshow_mark_of(handoff.this_process(), shape))

        assert handoff.the_shape_shown_in(tmp_path, by=handoff.this_process()) == shape

    def test_a_mark_names_the_process_beside_its_shape(self):
        assert handoff.slideshow_mark_of(handoff.this_process(), "portrait") == f"{_this_process()} portrait"

    def test_a_mark_from_before_marks_named_a_shape_could_be_showing_either(self, tmp_path: Path):
        _write(tmp_path, handoff.SHOWING, _this_process())

        assert handoff.the_shape_shown_in(tmp_path, by=handoff.this_process()) == "both"

    @pytest.mark.parametrize("mark", ["", "1234 5678", "1234 5678 portrait", "garbled"])
    def test_a_mark_naming_another_process_is_no_slideshow(self, tmp_path: Path, mark: str):
        _write(tmp_path, handoff.SHOWING, mark)

        assert handoff.the_shape_shown_in(tmp_path, by=handoff.this_process()) is None

    def test_a_mark_naming_a_shape_this_release_does_not_know_is_no_slideshow(self, tmp_path: Path):
        _write(tmp_path, handoff.SHOWING, f"{_this_process()} sideways")

        assert handoff.the_shape_shown_in(tmp_path, by=handoff.this_process()) is None

    def test_no_mark_is_no_slideshow(self, tmp_path: Path):
        assert handoff.the_shape_shown_in(tmp_path, by=handoff.this_process()) is None


class TestTheTakeover:
    def test_a_takeover_lands_whole_under_its_own_name(self, tmp_path: Path):
        handoff.hand_over(tmp_path, pid=4321, args=["--fun-time", "--x", "0"])

        assert [path.name for path in tmp_path.iterdir()] == [handoff.TAKEOVER]
        assert json.loads((tmp_path / handoff.TAKEOVER).read_text(encoding="utf-8")) == {
            "pid": 4321, "args": ["--fun-time", "--x", "0"]}

    def test_a_takeover_handed_over_is_the_takeover_taken(self, tmp_path: Path):
        handoff.hand_over(tmp_path, pid=4321, args=["--fun-time", "--x", "0"])

        assert handoff.take_the_takeover(tmp_path) == handoff.Takeover(4321, ["--fun-time", "--x", "0"])

    def test_a_takeover_waits_until_it_is_taken_and_is_gone_once_read(self, tmp_path: Path):
        handoff.hand_over(tmp_path, pid=4321, args=["--fun-time"])
        waited = handoff.a_takeover_waits_in(tmp_path)

        handoff.take_the_takeover(tmp_path)

        assert (waited, handoff.a_takeover_waits_in(tmp_path)) == (True, False)

    @pytest.mark.parametrize("written", ["not json", "[4321]", '{"pid": 4321}', '{"args": []}'])
    def test_a_takeover_that_does_not_read_as_one_is_refused_and_gone(self, tmp_path: Path, written: str):
        _write(tmp_path, handoff.TAKEOVER, written)

        with pytest.raises(ValueError, match="holds no takeover"):
            handoff.take_the_takeover(tmp_path)

        assert not handoff.a_takeover_waits_in(tmp_path)

    def test_no_takeover_is_none_taken(self, tmp_path: Path):
        assert handoff.take_the_takeover(tmp_path) is None


class TestTheSessionsClaim:
    def test_a_session_claims_the_osr2_by_its_own_process(self, tmp_path: Path):
        handoff.claim_the_osr2(tmp_path)

        assert (tmp_path / handoff.SESSION).read_text(encoding="utf-8") == _this_process()

    def test_a_live_sessions_claim_holds_the_osr2(self, tmp_path: Path):
        handoff.claim_the_osr2(tmp_path)

        assert handoff.a_session_claims_the_osr2(tmp_path)

    @pytest.mark.parametrize("claim", [
        "not a claim", "1234", "1234, 5678", "{this_process} more", "{this_process}, more"])
    def test_a_line_that_is_no_claim_holds_nothing(self, tmp_path: Path, claim: str):
        _write(tmp_path, handoff.SESSION, claim.format(this_process=_this_process()))

        assert not handoff.a_session_claims_the_osr2(tmp_path)

    def test_a_claim_left_by_a_session_that_has_ended_holds_nothing(self, tmp_path: Path):
        _write(tmp_path, handoff.SESSION, _a_process_that_has_ended())

        assert not handoff.a_session_claims_the_osr2(tmp_path)

    def test_no_claim_holds_nothing(self, tmp_path: Path):
        assert not handoff.a_session_claims_the_osr2(tmp_path)


class TestWhereTheyMeet:
    def test_a_production_checkout_meets_in_its_own_state_folder(self, tmp_path: Path):
        assert handoff.meeting_places(tmp_path / "origenerator") == (tmp_path / "origenerator" / "state",)

    def test_a_worktree_meets_in_its_own_state_folder_and_its_production_checkout_s(self, tmp_path: Path):
        production = tmp_path / "origenerator"
        worktree = production / ".claude" / "worktrees" / "my-branch"

        assert handoff.meeting_places(worktree) == (worktree / "state", production / "state")

    def test_a_session_hosting_a_worktree_finds_the_production_copy_open_on_its_library(self, tmp_path: Path):
        production = tmp_path / "origenerator"
        worktree = production / ".claude" / "worktrees" / "my-branch"
        _write(production / "state", handoff.OFFER, _this_process())

        assert [handoff.the_offer_in(place) for place in handoff.meeting_places(worktree)] == [
            None, handoff.Offer(handoff.this_process(), starting=False)]

    def test_a_session_hosting_a_worktree_claims_the_osr2_in_its_production_checkout_too(self, tmp_path: Path):
        production = tmp_path / "origenerator"
        worktree = production / ".claude" / "worktrees" / "my-branch"

        handoff.claim_the_osr2(*handoff.meeting_places(worktree))

        assert [handoff.a_session_claims_the_osr2(place) for place in (worktree / "state", production / "state")] == [
            True, True]

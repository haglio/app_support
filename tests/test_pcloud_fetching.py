from __future__ import annotations

from pathlib import Path

import pytest

from app_support.pcloud.api import PCloud, read_span
from app_support.pcloud.chunks import ChunkStore
from app_support.pcloud.fetching import A_DOWNLOADS_ATTEMPTS, Fetcher, NotInPCloud
from app_support.pcloud.testing import FakePCloud
from app_support.threading_utils import start_daemon_thread, wait_until

_CHUNK = 16
_VIDEO = "/library/video one.mp4"
_CONTENT = bytes(range(40))


def _fetcher(cloud: FakePCloud, folder: Path, **seams) -> Fetcher:
    return Fetcher(PCloud(cloud.origin, auth=cloud.auth), ChunkStore(folder), chunk_bytes=_CHUNK, **seams)


def test_a_chunk_not_yet_held_is_fetched_once_and_then_read_from_the_store(tmp_path: Path):
    with FakePCloud({_VIDEO: _CONTENT}) as cloud:
        fetcher = _fetcher(cloud, tmp_path)
        entry = fetcher.entry(_VIDEO)

        read = [fetcher.chunk(entry, 1), fetcher.chunk(entry, 1)]

        assert (read, cloud.downloads) == ([_CONTENT[16:32]] * 2, [(_VIDEO, 16, 32)])


def test_one_link_serves_every_chunk_until_it_nears_its_expiry_so_reading_on_costs_no_call_to_pcloud(tmp_path: Path):
    with FakePCloud({_VIDEO: _CONTENT}) as cloud:
        fetcher = _fetcher(cloud, tmp_path)
        entry = fetcher.entry(_VIDEO)

        fetcher.chunk(entry, 0)
        fetcher.chunk(entry, 1)

        assert cloud.calls == ["listfolder", "getfilelink"]


def test_a_link_within_a_minute_of_its_expiry_is_renewed_before_the_next_read(tmp_path: Path):
    with FakePCloud({_VIDEO: _CONTENT}) as cloud:
        moment = [cloud.links_expire - 3600]
        fetcher = _fetcher(cloud, tmp_path, now=lambda: moment[0])
        entry = fetcher.entry(_VIDEO)
        fetcher.chunk(entry, 0)
        moment[0] = cloud.links_expire - 30

        fetcher.chunk(entry, 1)

        assert cloud.calls == ["listfolder", "getfilelink", "getfilelink"]


def test_a_file_asked_about_again_soon_is_answered_without_asking_pcloud_again(tmp_path: Path):
    with FakePCloud({_VIDEO: _CONTENT}) as cloud:
        fetcher = _fetcher(cloud, tmp_path)

        assert (fetcher.entry(_VIDEO), cloud.calls) == (fetcher.entry(_VIDEO), ["listfolder"])


def test_a_chunk_another_app_is_fetching_is_waited_for_rather_than_fetched_twice(tmp_path: Path):
    with FakePCloud({_VIDEO: _CONTENT}) as cloud:
        theirs = []

        def while_waiting(_seconds: float) -> None:
            theirs[0].write(_CONTENT[16:32])
            theirs[0].keep()

        fetcher = _fetcher(cloud, tmp_path, sleep=while_waiting)
        entry = fetcher.entry(_VIDEO)
        theirs.append(ChunkStore(tmp_path).claim(entry.key, 1))

        assert (fetcher.chunk(entry, 1), cloud.downloads) == (_CONTENT[16:32], [])


def test_a_download_that_fails_is_tried_again_on_a_fresh_link_since_pcloud_can_end_a_link_early(tmp_path: Path):
    with FakePCloud({_VIDEO: _CONTENT}) as cloud:
        failures = [ConnectionResetError("the content host dropped the connection")]

        def read(url: str, start: int, stop: int) -> bytes:
            if failures:
                raise failures.pop()
            return read_span(url, start, stop)

        fetcher = _fetcher(cloud, tmp_path, read=read, sleep=lambda _seconds: None)
        entry = fetcher.entry(_VIDEO)

        assert (fetcher.chunk(entry, 1), cloud.calls) == (_CONTENT[16:32], ["listfolder", "getfilelink", "getfilelink"])


def test_a_download_that_keeps_failing_is_given_up_and_leaves_the_chunk_free_to_be_fetched_later(tmp_path: Path):
    with FakePCloud({_VIDEO: _CONTENT}) as cloud:
        def read(_url: str, _start: int, _stop: int) -> bytes:
            raise ConnectionResetError("the content host dropped the connection")

        fetcher = _fetcher(cloud, tmp_path, read=read, sleep=lambda _seconds: None)
        entry = fetcher.entry(_VIDEO)
        with pytest.raises(ConnectionResetError):
            fetcher.chunk(entry, 1)

        assert (cloud.calls.count("getfilelink"), ChunkStore(tmp_path).claim(entry.key, 1) is not None) == (
            A_DOWNLOADS_ATTEMPTS, True)


def test_a_span_that_comes_back_the_wrong_length_is_fetched_again_and_never_kept_since_hotel_wifi_answers_with_its_own_page(
        tmp_path: Path):
    with FakePCloud({_VIDEO: _CONTENT}) as cloud:
        answers = [b"<html>sign in to the hotel's wifi</html>"]

        def read(url: str, start: int, stop: int) -> bytes:
            return answers.pop() if answers else read_span(url, start, stop)

        fetcher = _fetcher(cloud, tmp_path, read=read, sleep=lambda _seconds: None)

        assert fetcher.chunk(fetcher.entry(_VIDEO), 1) == _CONTENT[16:32]


def test_planned_chunks_are_fetched_one_a_turn_in_the_order_planned_until_none_is_left(tmp_path: Path):
    with FakePCloud({_VIDEO: _CONTENT}) as cloud:
        fetcher = _fetcher(cloud, tmp_path)
        entry = fetcher.entry(_VIDEO)
        fetcher.plan("main", [(entry, 2), (entry, 0)])

        turns = [fetcher.work_one(), fetcher.work_one(), fetcher.work_one()]

        assert (turns, cloud.downloads) == ([True, True, False], [(_VIDEO, 32, 40), (_VIDEO, 0, 16)])


def test_each_planner_gets_its_turn_so_one_with_a_long_plan_never_starves_the_others(tmp_path: Path):
    other = "/library/video two.mp4"
    with FakePCloud({_VIDEO: _CONTENT, other: _CONTENT}) as cloud:
        fetcher = _fetcher(cloud, tmp_path)
        one, two = fetcher.entry(_VIDEO), fetcher.entry(other)
        fetcher.plan("first", [(one, 0), (one, 1)])
        fetcher.plan("second", [(two, 0)])

        while fetcher.work_one():
            pass

        assert cloud.downloads == [(_VIDEO, 0, 16), (other, 0, 16), (_VIDEO, 16, 32)]


def test_a_planners_new_plan_replaces_its_old_one_so_videos_skipped_past_are_not_fetched(tmp_path: Path):
    with FakePCloud({_VIDEO: _CONTENT}) as cloud:
        fetcher = _fetcher(cloud, tmp_path)
        entry = fetcher.entry(_VIDEO)
        fetcher.plan("main", [(entry, 0), (entry, 1)])
        fetcher.plan("main", [(entry, 2)])

        while fetcher.work_one():
            pass

        assert cloud.downloads == [(_VIDEO, 32, 40)]


def test_every_file_in_a_current_plan_is_kept_from_trimming_even_once_its_chunks_are_fetched(tmp_path: Path):
    other = "/library/video two.mp4"
    with FakePCloud({_VIDEO: _CONTENT, other: _CONTENT}) as cloud:
        fetcher = _fetcher(cloud, tmp_path)
        one, two = fetcher.entry(_VIDEO), fetcher.entry(other)
        fetcher.plan("first", [(one, 0)])
        fetcher.plan("second", [(two, 0)])
        while fetcher.work_one():
            pass
        fetcher.plan("second", [])

        assert fetcher.keeping() == {one.key}


def test_what_a_player_is_reading_through_is_fetched_before_anything_planned_for_later(tmp_path: Path):
    other = "/library/video two.mp4"
    with FakePCloud({_VIDEO: _CONTENT, other: _CONTENT}) as cloud:
        fetcher = _fetcher(cloud, tmp_path)
        playing, next_up = fetcher.entry(_VIDEO), fetcher.entry(other)
        fetcher.plan("main", [(next_up, 0), (next_up, 1)])
        fetcher.plan("read ahead", [(playing, 1), (playing, 2)], being_read=True)

        while fetcher.work_one():
            pass

        assert cloud.downloads == [(_VIDEO, 16, 32), (_VIDEO, 32, 40), (other, 0, 16), (other, 16, 32)]


def test_a_worker_fetches_whatever_is_planned_as_it_is_planned_until_the_fetcher_closes(tmp_path: Path):
    with FakePCloud({_VIDEO: _CONTENT}) as cloud:
        fetcher = _fetcher(cloud, tmp_path)
        entry = fetcher.entry(_VIDEO)
        worker = start_daemon_thread(target=fetcher.work_until_closed)

        fetcher.plan("main", [(entry, 0)])
        wait_until(lambda: len(cloud.downloads) == 1)
        fetcher.plan("main", [(entry, 2)])
        wait_until(lambda: len(cloud.downloads) == 2)
        fetcher.close()
        worker.join()

        assert cloud.downloads == [(_VIDEO, 0, 16), (_VIDEO, 32, 40)]


def test_a_planned_chunk_that_cannot_be_fetched_is_passed_by_and_the_worker_goes_on_to_the_next(tmp_path: Path):
    with FakePCloud({_VIDEO: _CONTENT}) as cloud:
        def read(url: str, start: int, stop: int) -> bytes:
            if start == 0:
                raise ConnectionResetError("the content host dropped the connection")
            return read_span(url, start, stop)

        fetcher = _fetcher(cloud, tmp_path, read=read, sleep=lambda _seconds: None)
        entry = fetcher.entry(_VIDEO)
        worker = start_daemon_thread(target=fetcher.work_until_closed)

        fetcher.plan("main", [(entry, 0), (entry, 2)])
        wait_until(lambda: cloud.downloads == [(_VIDEO, 32, 40)])
        fetcher.close()
        worker.join()


def test_the_files_of_one_folder_are_learned_in_one_listing_so_planning_many_of_its_videos_costs_one_call(tmp_path: Path):
    other = "/library/video two.mp4"
    with FakePCloud({_VIDEO: _CONTENT, other: _CONTENT[:20]}) as cloud:
        fetcher = _fetcher(cloud, tmp_path)

        sizes = [fetcher.entry(_VIDEO).size, fetcher.entry(other).size]

        assert (sizes, cloud.calls) == ([40, 20], ["listfolder"])


def test_a_file_in_a_folder_pcloud_does_not_have_is_not_in_pcloud(tmp_path: Path):
    with FakePCloud({_VIDEO: _CONTENT}) as cloud, pytest.raises(NotInPCloud):
        _fetcher(cloud, tmp_path).entry("/elsewhere/video one.mp4")


def test_a_file_that_arrived_after_its_folder_was_listed_is_found_by_listing_the_folder_again(tmp_path: Path):
    arrived = "/library/video two.mp4"
    with FakePCloud({_VIDEO: _CONTENT}) as cloud:
        moment = [1_000_000.0]
        fetcher = _fetcher(cloud, tmp_path, now=lambda: moment[0])
        fetcher.entry(_VIDEO)
        cloud.put(arrived, _CONTENT[:20])
        moment[0] += 3

        assert (fetcher.entry(arrived).size, cloud.calls) == (20, ["listfolder", "listfolder"])


def test_a_files_entry_carries_the_running_time_pcloud_read_for_it(tmp_path: Path):
    with FakePCloud({_VIDEO: _CONTENT}, durations={_VIDEO: 12.5}) as cloud:
        assert _fetcher(cloud, tmp_path).entry(_VIDEO).duration_s == 12.5

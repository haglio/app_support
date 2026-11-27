from __future__ import annotations

import json
import urllib.request
from pathlib import Path

import pytest

from app_support.pcloud.api import PCloud
from app_support.pcloud.chunks import ChunkStore
from app_support.pcloud.fetching import Fetcher
from app_support.pcloud.library import PLAY_FROM_PCLOUD, PCloudLibrary, Wish, from_settings
from app_support.pcloud.places import CloudPlaces
from app_support.pcloud.testing import FakePCloud
from app_support.threading_utils import wait_until

_CHUNK = 16
_CONTENT = bytes(range(40))


def _library(cloud: FakePCloud, folder: Path, **limits) -> PCloudLibrary:
    store = ChunkStore(folder / "cache")
    fetcher = Fetcher(PCloud(cloud.origin, auth=cloud.auth), store, chunk_bytes=_CHUNK)
    return PCloudLibrary(CloudPlaces({folder / "library": "/library"}), fetcher, store, chunk_bytes=_CHUNK,
                         **{"cap_bytes": 10 ** 9, "leave_free_bytes": 0, "workers": 0, **limits})


def test_a_file_kept_in_pcloud_plays_from_a_loopback_address_that_answers_with_its_bytes(tmp_path: Path):
    with FakePCloud({"/library/video one.mp4": _CONTENT}) as cloud, _library(cloud, tmp_path) as library:
        address = library.playable(tmp_path / "library" / "video one.mp4")

        with urllib.request.urlopen(address) as answer:
            assert (address.startswith("http://127.0.0.1:"), answer.read()) == (True, _CONTENT)


def test_a_file_in_no_folder_kept_in_pcloud_plays_from_where_it_is(tmp_path: Path):
    with FakePCloud({"/library/video one.mp4": _CONTENT}) as cloud, _library(cloud, tmp_path) as library:
        assert library.playable(tmp_path / "elsewhere" / "video.mp4") == str(tmp_path / "elsewhere" / "video.mp4")


def test_the_spans_wished_for_files_to_come_are_fetched_into_the_cache_ahead_of_any_player_asking(tmp_path: Path):
    with FakePCloud({"/library/video one.mp4": _CONTENT, "/library/video two.mp4": _CONTENT}) as cloud, \
            _library(cloud, tmp_path) as library:
        library.prefetch("main", [
            Wish(tmp_path / "library" / "video two.mp4", lambda entry: [(0, 16), (entry.size - 1, entry.size)]),
            Wish(tmp_path / "library" / "video one.mp4", lambda _entry: [(0, 1)]),
        ])
        library.plan_wished()
        while library.fetch_one():
            pass

        assert cloud.downloads == [("/library/video two.mp4", 0, 16), ("/library/video two.mp4", 32, 40),
                                   ("/library/video one.mp4", 0, 16)]


def test_a_wish_for_a_file_pcloud_lacks_or_one_kept_nowhere_in_pcloud_is_passed_over(tmp_path: Path):
    with FakePCloud({"/library/video one.mp4": _CONTENT}) as cloud, _library(cloud, tmp_path) as library:
        library.prefetch("main", [Wish(tmp_path / "library" / "gone.mp4", lambda _entry: [(0, 1)]),
                                  Wish(tmp_path / "elsewhere" / "video.mp4", lambda _entry: [(0, 1)]),
                                  Wish(tmp_path / "library" / "video one.mp4", lambda _entry: [(0, 1)])])
        library.plan_wished()
        while library.fetch_one():
            pass

        assert cloud.downloads == [("/library/video one.mp4", 0, 16)]


def test_a_library_at_work_fetches_what_is_wished_without_being_driven(tmp_path: Path):
    with FakePCloud({"/library/video one.mp4": _CONTENT}) as cloud, _library(cloud, tmp_path, workers=1) as library:
        library.prefetch("main", [Wish(tmp_path / "library" / "video one.mp4", lambda _entry: [(0, 40)])])

        wait_until(lambda: len(cloud.downloads) == 3)


def test_after_planning_the_cache_is_trimmed_to_its_cap_sparing_the_files_still_wished_for(tmp_path: Path):
    one, two = tmp_path / "library" / "video one.mp4", tmp_path / "library" / "video two.mp4"
    with FakePCloud({"/library/video one.mp4": _CONTENT, "/library/video two.mp4": _CONTENT}) as cloud, \
            _library(cloud, tmp_path, cap_bytes=16) as library:
        library.prefetch("main", [Wish(one, lambda _entry: [(0, 40)])])
        library.prefetch("portrait", [Wish(two, lambda _entry: [(0, 16)])])
        library.plan_wished()
        while library.fetch_one():
            pass
        library.prefetch("main", [])
        library.plan_wished()
        fetched_before = len(cloud.downloads)
        for video in (two, one):
            with urllib.request.urlopen(urllib.request.Request(library.playable(video), headers={"Range": "bytes=0-15"})) as answer:
                answer.read()

        assert cloud.downloads[fetched_before:] == [("/library/video one.mp4", 0, 16)]


def _settings(tmp_path: Path, **pcloud) -> dict:
    return {"library_root": str(tmp_path / "library"), "pcloud": {"cache_folder": str(tmp_path / "cache"), **pcloud}}


def _signed_in(tmp_path: Path, cloud: FakePCloud) -> Path:
    login = tmp_path / "pcloud_login.json"
    login.write_text(json.dumps({"api_host": cloud.origin, "auth": cloud.auth}), encoding="utf-8")
    return login


def test_playing_from_pcloud_is_off_unless_it_is_asked_for(tmp_path: Path):
    with FakePCloud({"/library/video one.mp4": _CONTENT}) as cloud:
        assert from_settings(environ={}, settings=_settings(tmp_path), login_file=_signed_in(tmp_path, cloud)) is None


@pytest.mark.parametrize(("environ", "asked"), [({PLAY_FROM_PCLOUD: "1"}, {}), ({}, {"play_from_pcloud": True})])
def test_asked_for_by_the_settings_or_by_a_preview_it_plays_the_librarys_files_from_pcloud_by_their_place_below_its_top(
        tmp_path: Path, environ: dict, asked: dict):
    with FakePCloud({f"{tmp_path.as_posix()}/library/videos/video one.mp4": _CONTENT}) as cloud:
        library = from_settings(environ=environ, settings=_settings(tmp_path, **asked),
                                login_file=_signed_in(tmp_path, cloud))
        with library, urllib.request.urlopen(library.playable(tmp_path / "library" / "videos" / "video one.mp4")) as answer:
            assert answer.read() == _CONTENT


def test_asked_for_on_a_computer_never_signed_in_to_pcloud_it_stays_off_and_says_why(
        tmp_path: Path, caplog: pytest.LogCaptureFixture):
    assert (from_settings(environ={PLAY_FROM_PCLOUD: "1"}, settings=_settings(tmp_path),
                          login_file=tmp_path / "never written.json"),
            [record.getMessage() for record in caplog.records]) == (
        None, ["Playing from pCloud was asked for, but this computer has not signed in to pCloud"])


def test_a_refusal_from_pcloud_while_planning_is_logged_rather_than_ending_the_planner_silently(
        tmp_path: Path, caplog: pytest.LogCaptureFixture):
    with FakePCloud({"/library/video one.mp4": _CONTENT}) as cloud:
        store = ChunkStore(tmp_path / "cache")
        refused = Fetcher(PCloud(cloud.origin, auth="a-token-nobody-issued"), store, chunk_bytes=_CHUNK)
        with PCloudLibrary(CloudPlaces({tmp_path / "library": "/library"}), refused, store, chunk_bytes=_CHUNK,
                           cap_bytes=10 ** 9, leave_free_bytes=0, workers=1) as library:
            library.prefetch("main", [Wish(tmp_path / "library" / "video one.mp4", lambda _entry: [(0, 1)])])
            wait_until(lambda: "Could not plan what to fetch from pCloud next" in caplog.text)


def test_a_wish_reaching_past_the_end_of_its_file_fetches_nothing_beyond_its_last_chunk(tmp_path: Path):
    with FakePCloud({"/library/video one.mp4": _CONTENT}) as cloud, _library(cloud, tmp_path) as library:
        library.prefetch("main", [Wish(tmp_path / "library" / "video one.mp4", lambda entry: [(16, entry.size * 3)])])
        library.plan_wished()
        while library.fetch_one():
            pass

        assert cloud.downloads == [("/library/video one.mp4", 16, 32), ("/library/video one.mp4", 32, 40)]


def test_asked_for_on_a_computer_never_signed_in_it_opens_the_sign_in(tmp_path: Path):
    opened: list[str] = []

    from_settings(environ={PLAY_FROM_PCLOUD: "1"}, settings=_settings(tmp_path), login_file=tmp_path / "never written.json",
                  when_not_signed_in=lambda: opened.append("the sign-in"))

    assert opened == ["the sign-in"]


def test_a_file_a_program_reads_whole_from_the_disk_is_copied_into_the_cache_once_and_read_there(tmp_path: Path):
    with FakePCloud({"/library/video one.mp4": _CONTENT}) as cloud, _library(cloud, tmp_path) as library:
        copies = [library.local_copy(tmp_path / "library" / "video one.mp4") for _ in range(2)]

        assert ([copy.read_bytes() for copy in copies], copies[0] == copies[1], len(cloud.downloads)) == (
            [_CONTENT, _CONTENT], True, 3)


def test_a_file_kept_nowhere_in_pcloud_is_read_where_it_is(tmp_path: Path):
    with FakePCloud({"/library/video one.mp4": _CONTENT}) as cloud, _library(cloud, tmp_path) as library:
        assert library.local_copy(tmp_path / "elsewhere" / "video.mp4") == tmp_path / "elsewhere" / "video.mp4"

from __future__ import annotations

import http.client
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from app_support.pcloud.api import PCloud, read_span
from app_support.pcloud.chunks import ChunkStore
from app_support.pcloud.fetching import Fetcher
from app_support.pcloud.places import CloudPlaces
from app_support.pcloud.server import FILES_READ_AHEAD_AT_ONCE, LoopbackServer
from app_support.pcloud.testing import FakePCloud

_CHUNK = 16
_VIDEO = "/library/video one.mp4"
_CONTENT = bytes(range(40))


def _fetcher(cloud: FakePCloud, folder: Path) -> Fetcher:
    return Fetcher(PCloud(cloud.origin, auth=cloud.auth), ChunkStore(folder), chunk_bytes=_CHUNK)


def _get(url: str, headers: dict[str, str] | None = None) -> tuple[int, dict[str, str], bytes]:
    with urllib.request.urlopen(urllib.request.Request(url, headers=headers or {})) as answer:
        return answer.status, dict(answer.headers), answer.read()


def test_a_player_asking_for_a_span_of_a_file_gets_just_those_bytes_as_a_partial_answer(tmp_path: Path):
    with FakePCloud({_VIDEO: _CONTENT}) as cloud, LoopbackServer(_fetcher(cloud, tmp_path), chunk_bytes=_CHUNK) as server:
        status, headers, body = _get(server.url_for(_VIDEO), {"Range": "bytes=10-20"})

        assert (status, headers["Content-Range"], body) == (206, "bytes 10-20/40", _CONTENT[10:21])


def test_a_player_asking_for_the_whole_file_gets_all_of_it(tmp_path: Path):
    with FakePCloud({_VIDEO: _CONTENT}) as cloud, LoopbackServer(_fetcher(cloud, tmp_path), chunk_bytes=_CHUNK) as server:
        status, headers, body = _get(server.url_for(_VIDEO))

        assert (status, headers["Content-Length"], body) == (200, "40", _CONTENT)


def test_a_file_pcloud_does_not_have_is_answered_as_not_found_so_the_player_gives_up_on_it_at_once(tmp_path: Path):
    with FakePCloud({_VIDEO: _CONTENT}) as cloud, LoopbackServer(_fetcher(cloud, tmp_path), chunk_bytes=_CHUNK) as server:
        with pytest.raises(urllib.error.HTTPError) as refused:
            _get(server.url_for("/library/gone.mp4"))

        assert refused.value.code == 404


def test_the_chunks_after_those_a_player_read_are_planned_so_its_next_read_finds_them_waiting(tmp_path: Path):
    with FakePCloud({_VIDEO: _CONTENT}) as cloud:
        fetcher = _fetcher(cloud, tmp_path)
        with LoopbackServer(fetcher, chunk_bytes=_CHUNK) as server:
            _get(server.url_for(_VIDEO), {"Range": "bytes=0-15"})

        while fetcher.work_one():
            pass

        assert cloud.downloads == [(_VIDEO, 0, 16), (_VIDEO, 16, 32), (_VIDEO, 32, 40)]


def test_only_the_files_read_most_recently_are_read_ahead_so_videos_left_long_ago_free_their_place(tmp_path: Path):
    videos = [f"/library/video {number}.mp4" for number in range(FILES_READ_AHEAD_AT_ONCE + 1)]
    with FakePCloud(dict.fromkeys(videos, _CONTENT)) as cloud:
        fetcher = _fetcher(cloud, tmp_path)
        with LoopbackServer(fetcher, chunk_bytes=_CHUNK) as server:
            for video in videos:
                _get(server.url_for(video), {"Range": "bytes=0-15"})

        assert fetcher.keeping() == {fetcher.entry(video).key for video in videos[1:]}


def test_an_answer_whose_download_fails_partway_ends_short_so_the_player_sees_it_fail_rather_than_wait(
        tmp_path: Path, caplog: pytest.LogCaptureFixture):
    with FakePCloud({_VIDEO: _CONTENT}) as cloud:
        def read(url: str, start: int, stop: int) -> bytes:
            if start:
                raise ConnectionResetError("the content host dropped the connection")
            return read_span(url, start, stop)

        fetcher = Fetcher(PCloud(cloud.origin, auth=cloud.auth), ChunkStore(tmp_path), chunk_bytes=_CHUNK, read=read,
                          sleep=lambda _seconds: None)
        with LoopbackServer(fetcher, chunk_bytes=_CHUNK) as server, pytest.raises(http.client.IncompleteRead) as cut:
            _get(server.url_for(_VIDEO))

        assert (cut.value.partial, [record.getMessage() for record in caplog.records]) == (
            _CONTENT[:16], ["Could not fetch /library/video one.mp4 for its player: the content host dropped the connection"])


class _APlayerThatLeft:
    def __init__(self) -> None:
        self.headers = {"Range": "bytes=0-39"}
        self.wfile = self
        self.written: list[bytes] = []

    def send_response(self, _status: int) -> None:
        pass

    def send_header(self, _name: str, _value: str) -> None:
        pass

    def end_headers(self) -> None:
        pass

    def write(self, data: bytes) -> None:
        if self.written:
            raise BrokenPipeError("the player closed its end, as it does to seek")
        self.written.append(data)


def test_a_player_that_leaves_partway_ends_its_answer_without_a_word_in_the_log_since_players_do_that_to_seek(
        tmp_path: Path, caplog: pytest.LogCaptureFixture):
    with FakePCloud({_VIDEO: _CONTENT}) as cloud:
        fetcher = _fetcher(cloud, tmp_path)
        with LoopbackServer(fetcher, chunk_bytes=_CHUNK) as server:
            player = _APlayerThatLeft()
            server.answer(player, _VIDEO)

        assert (player.written, caplog.records, [stop for _, _, stop in cloud.downloads]) == ([_CONTENT[:16]], [], [16, 32])


def test_a_file_pcloud_does_not_have_yet_is_served_from_this_computers_copy_while_there_is_one(tmp_path: Path):
    made_just_now = tmp_path / "library" / "video two.mp4"
    made_just_now.parent.mkdir()
    made_just_now.write_bytes(b"made just now")
    places = CloudPlaces({tmp_path / "library": "/library"})
    with FakePCloud({_VIDEO: _CONTENT}) as cloud, LoopbackServer(
            _fetcher(cloud, tmp_path / "cache"), chunk_bytes=_CHUNK, local_copy_of=places.local_path_of) as server:
        status, headers, body = _get(server.url_for("/library/video two.mp4"), {"Range": "bytes=5-8"})

        assert (status, headers["Content-Range"], body) == (206, "bytes 5-8/13", b"just")


def test_a_player_that_leaves_partway_through_this_computers_copy_ends_its_answer_there(tmp_path: Path):
    made_just_now = tmp_path / "library" / "video two.mp4"
    made_just_now.parent.mkdir()
    made_just_now.write_bytes(bytes(3 * 1024 * 1024))
    places = CloudPlaces({tmp_path / "library": "/library"})
    with FakePCloud({_VIDEO: _CONTENT}) as cloud, LoopbackServer(
            _fetcher(cloud, tmp_path / "cache"), chunk_bytes=_CHUNK, local_copy_of=places.local_path_of) as server:
        player = _APlayerThatLeft()
        player.headers = {}
        server.answer(player, "/library/video two.mp4")

        assert [len(piece) for piece in player.written] == [1024 * 1024]


def test_each_answer_is_logged_with_how_much_came_from_the_cache_how_much_was_fetched_and_how_soon_its_first_byte_went(
        tmp_path: Path, caplog: pytest.LogCaptureFixture):
    caplog.set_level("INFO", logger="app_support.pcloud.server")
    half = 512 * 1024
    moments = iter([100.0, 100.25, 200.0, 200.01])
    with FakePCloud({_VIDEO: bytes(2 * half)}) as cloud, LoopbackServer(
            Fetcher(PCloud(cloud.origin, auth=cloud.auth), ChunkStore(tmp_path), chunk_bytes=half),
            chunk_bytes=half, now=lambda: next(moments)) as server:
        _get(server.url_for(_VIDEO), {"Range": f"bytes=0-{half - 1}"})
        _get(server.url_for(_VIDEO), {"Range": f"bytes=0-{2 * half - 1}"})

    assert [record.getMessage() for record in caplog.records] == [
        "pCloud gave video one.mp4 bytes 0-524287: 0.0 MB from the cache, 0.5 MB fetched, the first byte after 250 ms",
        "pCloud gave video one.mp4 bytes 0-1048575: 0.5 MB from the cache, 0.5 MB fetched, the first byte after 10 ms",
    ]

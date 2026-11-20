from __future__ import annotations

import os
from pathlib import Path

from app_support.file_channel import publish_whole
from app_support.written_file import STAMPED_TOO_LATELY_TO_TELL_NS, ReadWhenChanged, WrittenFile


class LongAfterTheFileWasStamped:
    def __init__(self, path: Path) -> None:
        self._path = path

    def __call__(self) -> int:
        return self._path.stat().st_mtime_ns + 10 * STAMPED_TOO_LATELY_TO_TELL_NS


class JustAfterTheFileWasStamped(LongAfterTheFileWasStamped):
    def __call__(self) -> int:
        return self._path.stat().st_mtime_ns + STAMPED_TOO_LATELY_TO_TELL_NS // 2


def _a_file_long_written(tmp_path: Path) -> WrittenFile:
    path = tmp_path / "hud.json"
    return WrittenFile(path, now_ns=LongAfterTheFileWasStamped(path))


def test_a_file_reads_as_perhaps_written_until_it_has_been_read(tmp_path):
    file = _a_file_long_written(tmp_path)
    publish_whole(file.path, "one")

    assert file.may_have_been_written()
    assert file.may_have_been_written()
    file.was_read()

    assert not file.may_have_been_written()


def test_a_second_write_is_told_from_the_first_though_windows_stamped_both_with_one_time(tmp_path):
    file = _a_file_long_written(tmp_path)
    publish_whole(file.path, "one")
    first = file.path.stat()
    file.may_have_been_written()
    file.was_read()

    publish_whole(file.path, "two")
    os.utime(file.path, ns=(first.st_atime_ns, first.st_mtime_ns))

    assert file.may_have_been_written()


def test_a_file_stamped_too_lately_to_tell_two_writes_apart_goes_on_reading_as_perhaps_written(
        tmp_path):
    path = tmp_path / "hud.json"
    file = WrittenFile(path, now_ns=JustAfterTheFileWasStamped(path))
    path.write_text("one", encoding="utf-8")

    file.may_have_been_written()
    file.was_read()

    assert file.may_have_been_written()


def test_a_file_taken_away_reads_as_perhaps_written_once_and_holds_nothing(tmp_path):
    file = _a_file_long_written(tmp_path)
    publish_whole(file.path, "one")
    file.may_have_been_written()
    file.was_read()

    file.path.unlink()

    assert file.may_have_been_written()
    assert not file.holds_something
    file.was_read()
    assert not file.may_have_been_written()


def _counting_reader(reads: list[Path]):
    def read(path: Path) -> str | None:
        reads.append(path)
        return path.read_text(encoding="utf-8") if path.exists() else None
    return read


def test_a_file_asked_for_many_times_is_read_again_only_after_it_is_written(tmp_path):
    path = tmp_path / "state.txt"
    publish_whole(path, "before")
    reads: list[Path] = []
    kept = ReadWhenChanged(path, _counting_reader(reads), now_ns=LongAfterTheFileWasStamped(path))

    before = {kept.latest() for _ask in range(5)}
    publish_whole(path, "after")
    after = {kept.latest() for _ask in range(5)}

    assert (before, after, len(reads)) == ({"before"}, {"after"}, 2)


def test_a_file_not_there_is_asked_of_the_reader_once_until_it_appears(tmp_path):
    path = tmp_path / "state.txt"
    reads: list[Path] = []
    kept = ReadWhenChanged(path, _counting_reader(reads), now_ns=LongAfterTheFileWasStamped(path))

    missing = [kept.latest() for _ask in range(3)]
    publish_whole(path, "there")

    assert (missing, kept.latest(), len(reads)) == ([None, None, None], "there", 2)


def test_a_read_that_failed_keeps_the_last_value_and_is_tried_again_on_the_next_ask(tmp_path):
    path = tmp_path / "state.txt"
    publish_whole(path, "one")
    answers: list[object] = [PermissionError("held by its writer"), "one"]
    reads: list[Path] = []

    def read(read_path: Path) -> str:
        reads.append(read_path)
        answer = answers.pop(0)
        if isinstance(answer, OSError):
            raise answer
        return answer

    kept = ReadWhenChanged(path, read, now_ns=LongAfterTheFileWasStamped(path))

    assert (kept.latest(), kept.latest(), kept.latest(), len(reads)) == (None, "one", "one", 2)


def test_a_reader_handed_a_way_to_date_the_file_dates_it_that_way_alone(tmp_path):
    path = tmp_path / "state.txt"
    publish_whole(path, "one")
    dated: list[Path] = []

    def from_the_folders_listing(asked: Path) -> os.stat_result:
        dated.append(asked)
        return os.stat(asked)

    kept = ReadWhenChanged(path, _counting_reader([]), now_ns=LongAfterTheFileWasStamped(path),
                           stat=from_the_folders_listing)

    assert ([kept.latest(), kept.latest()], dated) == (["one", "one"], [path, path])


def test_a_file_written_twice_in_place_inside_one_tick_of_the_file_clock_is_followed(tmp_path):
    path = tmp_path / "state.txt"
    path.write_text("0", encoding="utf-8")
    one_stamp = path.stat()
    kept = ReadWhenChanged(path, _counting_reader([]), now_ns=JustAfterTheFileWasStamped(path))
    heard = [kept.latest()]

    path.write_text("1", encoding="utf-8")
    os.utime(path, ns=(one_stamp.st_atime_ns, one_stamp.st_mtime_ns))
    heard.append(kept.latest())

    assert heard == ["0", "1"]

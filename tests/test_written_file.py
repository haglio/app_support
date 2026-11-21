from __future__ import annotations

import os
from pathlib import Path

from app_support.file_channel import publish_whole
from app_support.written_file import (
    STAMPED_TOO_LATELY_TO_TELL_NS,
    ReadEachWhenChanged,
    ReadWhenChanged,
    WrittenFile,
)


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


_A_TICK_NS = 32_000_000


class ATenthOfASecondAfterTheFileWasStamped(LongAfterTheFileWasStamped):
    def __call__(self) -> int:
        return self._path.stat().st_mtime_ns + 100_000_000


def test_a_reader_told_a_shorter_while_reads_a_file_stamped_since_only_inside_that_while(tmp_path):
    path = tmp_path / "status.txt"
    publish_whole(path, "one")
    file = WrittenFile(path, now_ns=ATenthOfASecondAfterTheFileWasStamped(path),
                       too_lately_ns=_A_TICK_NS)

    file.may_have_been_written()
    file.was_read()

    assert not file.may_have_been_written()


def test_each_of_many_files_read_with_a_shorter_while_is_read_once_until_written_again(tmp_path):
    path = tmp_path / "status.txt"
    publish_whole(path, "one")
    reads: list[Path] = []
    each = ReadEachWhenChanged(_counting_reader(reads), most=8, too_lately_ns=_A_TICK_NS,
                               now_ns=ATenthOfASecondAfterTheFileWasStamped(path))

    asked = [each.latest(path) for _ask in range(4)]

    assert (asked, reads) == (["one"] * 4, [path])


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


class LongAfterAnyStamp:
    def __call__(self) -> int:
        return 2**62


def test_a_look_taken_before_the_file_was_written_again_keeps_it_unread(tmp_path):
    path = tmp_path / "state.txt"
    publish_whole(path, "one")
    kept = ReadWhenChanged(path, _counting_reader([]), now_ns=LongAfterAnyStamp())

    looked = kept.look()
    publish_whole(path, "two")
    looked.keep("one, read off the window's thread")

    assert (looked.fresh, kept.look().fresh, kept.latest()) == (False, False, "two")


def test_a_look_at_a_file_unchanged_since_its_read_hands_back_what_was_read(tmp_path):
    path = tmp_path / "state.txt"
    publish_whole(path, "one")
    kept = ReadWhenChanged(path, _counting_reader([]), now_ns=LongAfterAnyStamp())
    kept.look().keep("read later")

    looked = kept.look()

    assert (looked.fresh, looked.value) == (True, "read later")


def test_each_of_many_files_is_read_again_only_after_it_is_written(tmp_path):
    one, two = tmp_path / "one.txt", tmp_path / "two.txt"
    publish_whole(one, "first")
    publish_whole(two, "second")
    reads: list[Path] = []
    each = ReadEachWhenChanged(_counting_reader(reads), most=8, now_ns=LongAfterAnyStamp())

    before = [each.latest(path) for path in (one, two, one, two)]
    publish_whole(one, "first again")
    after = [each.latest(path) for path in (one, two)]

    assert (before, after, reads) == (["first", "second", "first", "second"],
                                      ["first again", "second"], [one, two, one])


def test_one_file_read_several_ways_is_kept_once_for_each_way(tmp_path):
    path = tmp_path / "picture.txt"
    publish_whole(path, "abc")
    reads: list[tuple[Path, int]] = []

    def first_letters(key: tuple[Path, int]) -> str:
        reads.append(key)
        return key[0].read_text(encoding="utf-8")[:key[1]]

    each = ReadEachWhenChanged(first_letters, most=8, path_of=lambda key: key[0],
                               now_ns=LongAfterAnyStamp())

    asked = [each.latest((path, size)) for size in (1, 2, 1, 2)]

    assert (asked, reads) == (["a", "ab", "a", "ab"], [(path, 1), (path, 2)])


def test_the_files_asked_for_least_lately_are_let_go_beyond_the_most_kept(tmp_path):
    paths = [tmp_path / f"{name}.txt" for name in ("one", "two", "three")]
    for path in paths:
        publish_whole(path, path.stem)
    reads: list[Path] = []
    each = ReadEachWhenChanged(_counting_reader(reads), most=2, now_ns=LongAfterAnyStamp())
    one, two, three = paths

    for path in (one, two, one, three, one, two):
        each.latest(path)

    assert (reads, len(each)) == ([one, two, three, two], 2)


def test_a_look_says_whether_the_file_holds_anything_to_read(tmp_path):
    there, empty, gone = tmp_path / "there.txt", tmp_path / "empty.txt", tmp_path / "gone.txt"
    publish_whole(there, "one")
    empty.write_bytes(b"")

    looked = [ReadWhenChanged(path, _counting_reader([]), now_ns=LongAfterAnyStamp()).look()
              for path in (there, empty, gone)]

    assert [look.holds_something for look in looked] == [True, False, False]


def test_files_read_off_the_calling_thread_are_held_through_looks_alone(tmp_path):
    path = tmp_path / "picture.txt"
    publish_whole(path, "one")
    each: ReadEachWhenChanged[Path, str] = ReadEachWhenChanged(most=8, now_ns=LongAfterAnyStamp())

    each.look(path).keep("one, made on another thread")
    unchanged = each.look(path)
    publish_whole(path, "two")

    assert ((unchanged.fresh, unchanged.value), each.look(path).fresh) == (
        (True, "one, made on another thread"), False)

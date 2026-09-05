"""The flag, the stamp and the key=value record: what app_support.file_channel
added when the broker's and Fun Time's readers of the same files became one."""
from __future__ import annotations

import logging
from pathlib import Path
from unittest.mock import MagicMock, patch

from app_support.file_channel import (
    publish_stamp,
    read_flag,
    read_key_values,
    read_paused_state,
    stamp_age,
    write_flag,
)


class TestReadFlag:
    def test_a_one_is_true_and_a_zero_is_false_whatever_the_default(self, tmp_path: Path):
        path = tmp_path / "flag.txt"
        for default in (True, False):
            path.write_text("1", encoding="utf-8")
            assert read_flag(path, default=default) is True
            path.write_text("0", encoding="utf-8")
            assert read_flag(path, default=default) is False

    def test_a_file_that_is_not_there_is_the_default(self, tmp_path: Path):
        assert read_flag(tmp_path / "flag.txt", default=True) is True
        assert read_flag(tmp_path / "flag.txt", default=False) is False

    def test_anything_that_is_neither_character_is_the_default(self, tmp_path: Path):
        """The test is for the character that means the switch was thrown: a
        file left half-written, or holding something nobody here recognises,
        is not a decision."""
        path = tmp_path / "flag.txt"
        for text in ("", "   ", "yes please", "true"):
            path.write_text(text, encoding="utf-8")
            assert read_flag(path, default=True) is True
            assert read_flag(path, default=False) is False

    def test_a_bom_and_surrounding_whitespace_do_not_hide_the_character(self, tmp_path: Path):
        # PowerShell writes some of these files, and PowerShell leaves a BOM.
        path = tmp_path / "flag.txt"
        path.write_bytes(b"\xef\xbb\xbf 0 \r\n")

        assert read_flag(path, default=True) is False

    def test_an_unreadable_path_is_the_default_and_says_so(self, tmp_path: Path):
        logger = MagicMock(spec=logging.Logger)

        assert read_flag(tmp_path, default=True, logger=logger) is True  # a directory

        logger.exception.assert_called_once()

    def test_paused_is_the_flag_that_defaults_to_running(self, tmp_path: Path):
        path = tmp_path / "paused.txt"

        assert read_paused_state(path) is False
        write_flag(path, True)
        assert read_paused_state(path) is True


class TestWriteFlag:
    def test_it_lands_as_the_one_character_the_readers_look_for(self, tmp_path: Path):
        path = tmp_path / "state" / "flag.txt"

        assert write_flag(path, True)
        assert path.read_text(encoding="utf-8") == "1"
        assert write_flag(path, False)
        assert path.read_text(encoding="utf-8") == "0"

    def test_it_is_published_whole(self, tmp_path: Path):
        # The one-character file has the same blank window as any other on a
        # truncate-and-write, and blank reads as the default -- enabled, for
        # the flag being turned off.
        path = tmp_path / "flag.txt"
        with patch("app_support.file_channel.os.replace") as replace:
            write_flag(path, False)

        assert replace.called


class TestStamps:
    def test_the_stamp_is_the_wall_clock_as_text(self, tmp_path: Path):
        path = tmp_path / "state" / "heartbeat.txt"

        with patch("app_support.file_channel.time.time", return_value=123.45):
            assert publish_stamp(path)

        assert path.read_text(encoding="utf-8") == "123.45"

    def test_the_age_is_measured_from_the_stamp(self, tmp_path: Path):
        path = tmp_path / "heartbeat.txt"
        publish_stamp(path, 100.0)

        assert stamp_age(path, now=102.5) == 2.5

    def test_never_stamped_and_torn_both_read_as_none(self, tmp_path: Path):
        # None rather than infinity, so "stale" and "never" stay apart; and a
        # stamp read mid-publish is not an old one.
        assert stamp_age(tmp_path / "missing.txt", now=100.0) is None
        torn = tmp_path / "torn.txt"
        torn.write_text("not-a-float", encoding="utf-8")
        assert stamp_age(torn, now=100.0) is None

    def test_a_stamp_with_a_bom_still_reads(self, tmp_path: Path):
        path = tmp_path / "rx.txt"
        path.write_text("100.0", encoding="utf-8-sig")

        assert stamp_age(path, now=101.0) == 1.0


class TestReadKeyValues:
    def test_it_reads_one_pair_per_line(self, tmp_path: Path):
        path = tmp_path / "status.txt"
        path.write_text("video=demo.mp4\nposition_ms=42\n", encoding="utf-8")

        assert read_key_values(path) == {"video": "demo.mp4", "position_ms": "42"}

    def test_the_value_keeps_every_equals_sign_after_the_first(self, tmp_path: Path):
        path = tmp_path / "status.txt"
        path.write_text("video=C:/clips/a=b.mp4\n", encoding="utf-8")

        assert read_key_values(path) == {"video": "C:/clips/a=b.mp4"}

    def test_a_line_without_a_pair_is_skipped(self, tmp_path: Path):
        path = tmp_path / "status.txt"
        path.write_text("just words\nstate=looping\n", encoding="utf-8")

        assert read_key_values(path) == {"state": "looping"}

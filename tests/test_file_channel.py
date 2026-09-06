"""Tests for app_support.file_channel: the queue, the claim, the flag and the whole publish."""
from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

from app_support.file_channel import (
    append_command,
    consume_command_file,
    publish_whole,
    read_paused_state,
)


def test_append_command_queues_a_verb_without_losing_the_one_before_it(tmp_path: Path):
    """The channel is a queue, not a slot: two writers in one drain window must
    both be heard, and a writer that overwrites silently eats the other's verb."""
    path = tmp_path / "cmd.txt"

    assert append_command(path, "SET_ACTIVE 1")
    assert append_command(path, "SET_TCODE_ENABLED 0")

    assert consume_command_file(path, uppercase=False) == ["SET_ACTIVE 1", "SET_TCODE_ENABLED 0"]


def test_append_command_starts_a_line_of_its_own_after_an_unterminated_write(tmp_path: Path):
    """An orchestrator that writes the file whole rarely bothers with a trailing
    newline, and appending straight onto that welds the two verbs into one word
    that matches neither — silently losing both.  Observed as exactly that: a
    "NEXT" written whole, an appended flag, and a player that never navigated.
    """
    path = tmp_path / "cmd.txt"
    path.write_text("NEXT", encoding="utf-8")  # no trailing newline

    assert append_command(path, "SET_ACTIVE 1")

    assert consume_command_file(path, uppercase=False) == ["NEXT", "SET_ACTIVE 1"]


def test_append_command_does_not_double_space_a_terminated_file(tmp_path: Path):
    path = tmp_path / "cmd.txt"
    path.write_text("NEXT\n", encoding="utf-8")

    assert append_command(path, "PREV")

    assert path.read_text(encoding="utf-8") == "NEXT\nPREV\n"


def test_append_command_creates_the_file_and_its_directory(tmp_path: Path):
    path = tmp_path / "state" / "cmd.txt"

    assert append_command(path, "QUIT")

    assert consume_command_file(path) == ["QUIT"]


def test_append_command_retries_past_a_drain_then_gives_up(tmp_path: Path):
    """The orchestrator drains this file ~20x/s, and a write overlapping a drain
    hits a Windows sharing violation.  Retrying makes that a millisecond's wait;
    a file locked for longer drops the line rather than raising into a run loop —
    the next command lands, where an exception would take the loop down.
    """
    path = tmp_path / "cmd.txt"

    with patch("pathlib.Path.open", side_effect=OSError("locked")):
        assert append_command(path, "NEXT", attempts=2, delay_s=0) is False

    assert consume_command_file(path) == []


def test_consume_returns_empty_list_when_file_missing(tmp_path: Path):
    path = tmp_path / "cmd.txt"

    result = consume_command_file(path)

    assert result == []


def test_consume_returns_empty_list_when_file_empty(tmp_path: Path):
    path = tmp_path / "cmd.txt"
    path.write_text("", encoding="utf-8")

    result = consume_command_file(path)

    assert result == []


def test_consume_returns_single_command(tmp_path: Path):
    path = tmp_path / "cmd.txt"
    path.write_text("NEXT", encoding="utf-8")

    result = consume_command_file(path)

    assert result == ["NEXT"]


def test_consume_returns_multiple_commands_from_multiline(tmp_path: Path):
    path = tmp_path / "cmd.txt"
    path.write_text("RESUME\nHUD_ON", encoding="utf-8")

    result = consume_command_file(path)

    assert result == ["RESUME", "HUD_ON"]


def test_consume_skips_blank_lines(tmp_path: Path):
    path = tmp_path / "cmd.txt"
    path.write_text("RESUME\n\nHUD_ON\n", encoding="utf-8")

    result = consume_command_file(path)

    assert result == ["RESUME", "HUD_ON"]


def test_consume_takes_the_queue_away(tmp_path: Path):
    """Claimed by rename, not read-then-truncated: the truncate had a gap one
    verb wide, and a handoff verb appended into it was erased unread."""
    path = tmp_path / "cmd.txt"
    path.write_text("NEXT", encoding="utf-8")

    consume_command_file(path)

    assert not path.exists()
    assert not path.with_suffix(path.suffix + ".consuming").exists()


def test_a_verb_appended_after_a_consume_is_read_by_the_next(tmp_path: Path):
    path = tmp_path / "cmd.txt"
    path.write_text("NEXT", encoding="utf-8")

    assert consume_command_file(path) == ["NEXT"]
    append_command(path, "PAUSE")

    assert consume_command_file(path) == ["PAUSE"]


def test_consume_uppercases_commands(tmp_path: Path):
    path = tmp_path / "cmd.txt"
    path.write_text("resume\nhud_on", encoding="utf-8")

    result = consume_command_file(path)

    assert result == ["RESUME", "HUD_ON"]


def test_consume_preserves_case_when_uppercase_disabled(tmp_path: Path):
    cmd_file = tmp_path / "cmd.txt"
    cmd_file.write_text("PLAY_FILE C:/Videos/MyClip.mp4\n", encoding="utf-8")

    commands = consume_command_file(cmd_file, uppercase=False)

    assert commands == ["PLAY_FILE C:/Videos/MyClip.mp4"]


def test_consume_strips_a_byte_order_mark(tmp_path: Path):
    # A hand-edited command file (Notepad, PowerShell redirection) carries a BOM
    # that would otherwise fuse onto the first verb and match nothing.
    path = tmp_path / "cmd.txt"
    path.write_text("NEXT", encoding="utf-8-sig")

    assert consume_command_file(path) == ["NEXT"]


def test_read_paused_state_reads_flag(tmp_path: Path):
    paused_file = tmp_path / "paused.txt"

    assert read_paused_state(paused_file) is False

    paused_file.write_text("1", encoding="utf-8")
    assert read_paused_state(paused_file) is True

    paused_file.write_text("0", encoding="utf-8")
    assert read_paused_state(paused_file) is False


def test_read_paused_state_strips_a_byte_order_mark(tmp_path: Path):
    paused_file = tmp_path / "paused.txt"
    paused_file.write_text("1", encoding="utf-8-sig")

    assert read_paused_state(paused_file) is True


def test_publish_retries_past_a_reader_holding_the_file_open(tmp_path: Path):
    """Windows refuses to replace a file another process has open, so a publish
    landing inside one of the reader's polls raises.  Riding out that microsecond
    delivers the record instead of dropping it."""
    path = tmp_path / "status.txt"
    path.write_text("old\n", encoding="utf-8")
    real_replace = os.replace
    calls = []

    def flaky_replace(src, dst):
        calls.append(src)
        if len(calls) == 1:
            raise PermissionError(5, "Access is denied")
        real_replace(src, dst)

    with patch("app_support.file_channel.os.replace", side_effect=flaky_replace):
        assert publish_whole(path, "new\n") is True

    assert len(calls) == 2
    assert path.read_text(encoding="utf-8") == "new\n"

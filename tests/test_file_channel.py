from __future__ import annotations

import os
import threading
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import call, patch

import pytest

from app_support import file_channel
from app_support.file_channel import (
    append_command,
    consume_command_file,
    publish_whole,
    read_paused_state,
    read_whole,
    retried_while_held,
    write_flag,
    write_whole,
)

_GENERIC_READ = 0x80000000
_SHARED_WITH_NOBODY = 0
_CREATE_IF_MISSING = 4


def test_append_command_queues_a_verb_without_losing_the_one_before_it(tmp_path: Path):
    path = tmp_path / "cmd.txt"

    assert append_command(path, "SET_ACTIVE 1")
    assert append_command(path, "SET_TCODE_ENABLED 0")

    assert consume_command_file(path, uppercase=False) == ["SET_ACTIVE 1", "SET_TCODE_ENABLED 0"]


def test_append_command_starts_a_line_of_its_own_after_an_unterminated_write(tmp_path: Path):
    path = tmp_path / "cmd.txt"
    path.write_text("NEXT", encoding="utf-8")

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


def test_a_verb_the_drain_outlasts_is_given_up_with_false_never_a_raise_into_the_loop(tmp_path: Path, held_open):
    path = tmp_path / "cmd.txt"

    with held_open(path, access=_GENERIC_READ, share=_SHARED_WITH_NOBODY,
                   disposition=_CREATE_IF_MISSING):
        assert append_command(path, "NEXT", attempts=2, delay_s=0) is False

    assert consume_command_file(path) == []


def test_a_verb_waits_out_a_hold_that_outlasts_many_quick_tries(tmp_path: Path, held_open):
    path = tmp_path / "cmd.txt"

    with held_open(path, access=_GENERIC_READ, share=_SHARED_WITH_NOBODY,
                   disposition=_CREATE_IF_MISSING) as let_go:
        threading.Timer(0.2, let_go).start()
        assert append_command(path, "LANDSCAPE_OPEN_SLIDESHOW")

    assert consume_command_file(path) == ["LANDSCAPE_OPEN_SLIDESHOW"]


def test_a_verb_given_up_on_is_logged_by_name(tmp_path: Path, held_open, caplog):
    path = tmp_path / "cmd.txt"

    with held_open(path, access=_GENERIC_READ, share=_SHARED_WITH_NOBODY,
                   disposition=_CREATE_IF_MISSING):
        assert append_command(path, "NEXT", attempts=2, delay_s=0) is False

    assert "NEXT" in caplog.text
    assert str(path) in caplog.text


def test_two_senders_at_once_lose_neither_ones_commands(tmp_path: Path):
    path = tmp_path / "cmd.txt"
    sent_by_each = 400
    both_ready = threading.Barrier(2)

    def send(sender: str) -> None:
        both_ready.wait()
        for number in range(sent_by_each):
            append_command(path, f"{sender} {number}")

    senders = [threading.Thread(target=send, args=(sender,)) for sender in ("NEXT", "PREV")]
    for sender in senders:
        sender.start()
    for sender in senders:
        sender.join()

    arrived = consume_command_file(path, uppercase=False)
    assert sorted(arrived) == sorted(f"{sender} {number}" for sender in ("NEXT", "PREV")
                                     for number in range(sent_by_each))


def test_a_channel_nobody_has_written_to_yet_holds_no_commands(tmp_path: Path):
    path = tmp_path / "cmd.txt"

    result = consume_command_file(path)

    assert result == []


def test_an_emptied_channel_holds_no_commands(tmp_path: Path):
    path = tmp_path / "cmd.txt"
    path.write_text("", encoding="utf-8")

    result = consume_command_file(path)

    assert result == []


def test_one_written_command_comes_back_whole(tmp_path: Path):
    path = tmp_path / "cmd.txt"
    path.write_text("NEXT", encoding="utf-8")

    result = consume_command_file(path)

    assert result == ["NEXT"]


def test_commands_come_back_one_per_line_in_the_order_written(tmp_path: Path):
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
    path = tmp_path / "cmd.txt"
    path.write_text("NEXT", encoding="utf-8")

    consume_command_file(path)

    assert not path.exists()
    assert not path.with_suffix(path.suffix + ".consuming").exists()


def test_a_verb_appended_while_the_queue_is_being_read_is_drained_next_tick(tmp_path: Path):
    path = tmp_path / "cmd.txt"
    path.write_text("NEXT", encoding="utf-8")
    read = file_channel._read_text

    def a_late_verb_arrives_as_the_queue_is_read(claimed: Path) -> str:
        text = read(claimed)
        append_command(path, "LATE")
        return text

    with patch("app_support.file_channel._read_text", side_effect=a_late_verb_arrives_as_the_queue_is_read):
        assert consume_command_file(path) == ["NEXT"]

    assert consume_command_file(path) == ["LATE"]


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


def test_with_uppercase_off_nothing_is_folded_the_keyword_is_the_callers_to_fold(tmp_path: Path):
    cmd_file = tmp_path / "cmd.txt"
    cmd_file.write_text("play_file C:/Videos/MyClip.mp4\n", encoding="utf-8")

    commands = consume_command_file(cmd_file, uppercase=False)

    assert commands == ["play_file C:/Videos/MyClip.mp4"]


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


def test_pause_is_a_state_read_again_and_again_not_an_event_consumed_once(tmp_path: Path):
    paused = tmp_path / "paused.txt"
    write_flag(paused, True)

    assert [read_paused_state(paused) for _ in range(3)] == [True, True, True]


def test_read_paused_state_strips_a_byte_order_mark(tmp_path: Path):
    paused_file = tmp_path / "paused.txt"
    paused_file.write_text("1", encoding="utf-8-sig")

    assert read_paused_state(paused_file) is True


def test_publish_retries_past_a_reader_holding_the_file_open(tmp_path: Path):
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


def test_a_publish_keeps_the_line_endings_the_format_asks_for(tmp_path: Path):
    path = tmp_path / "rows.csv"

    assert publish_whole(path, "one\r\ntwo\r\n", newline="") is True

    assert path.read_bytes() == b"one\r\ntwo\r\n"


def test_a_rewrite_that_could_not_land_raises_since_an_unread_false_reads_as_landed(tmp_path: Path):
    path = tmp_path / "session.json"

    with (
        patch("app_support.file_channel.os.replace", side_effect=OSError("held")),
        pytest.raises(OSError, match="could not replace"),
    ):
        write_whole(path, "{}", attempts=1)


def test_a_write_that_landed_says_nothing(tmp_path: Path):
    path = tmp_path / "session.json"

    assert write_whole(path, '{"act": "alpha"}\n') is None

    assert path.read_text(encoding="utf-8") == '{"act": "alpha"}\n'
def test_a_file_that_is_not_there_is_reported_at_once_rather_than_waited_for(tmp_path: Path):
    with (
        patch("app_support.file_channel.time.sleep") as waited,
        pytest.raises(FileNotFoundError),
    ):
        read_whole(tmp_path / "never-written.txt")

    waited.assert_not_called()


def test_an_act_refused_while_its_file_is_held_is_tried_again_on_the_callers_budget():
    answers = iter([PermissionError(13, "Permission denied"), PermissionError(13, "Permission denied"),
                    "moved"])

    def move():
        answer = next(answers)
        if isinstance(answer, Exception):
            raise answer
        return answer

    with patch("app_support.file_channel.time.sleep") as waited:
        assert retried_while_held(move, attempts=3, delay_s=0.2) == "moved"

    assert waited.call_args_list == [call(0.2), call(0.2)]


def test_a_refusal_that_outlasts_the_callers_attempts_is_raised():
    tried = []

    def move():
        tried.append(move)
        raise PermissionError(13, "Permission denied")

    with patch("app_support.file_channel.time.sleep"), pytest.raises(PermissionError):
        retried_while_held(move, attempts=4, delay_s=0.2)

    assert len(tried) == 4


def test_a_write_makes_the_directory_it_writes_into(tmp_path: Path):
    path = tmp_path / "not" / "yet" / "record.json"

    write_whole(path, "{}")

    assert path.is_file()


def test_a_write_that_dies_part_way_leaves_the_old_file_whole(tmp_path: Path):
    path = tmp_path / "record.json"
    path.write_text("the old one", encoding="utf-8")

    with (
        patch("app_support.file_channel.os.replace", side_effect=OSError("interrupted")),
        pytest.raises(OSError, match="could not replace"),
    ):
        write_whole(path, "the new one", attempts=1)

    assert path.read_text(encoding="utf-8") == "the old one"


def test_a_write_that_dies_part_way_leaves_no_temp_file_that_reads_as_someones(tmp_path: Path):
    path = tmp_path / "record.json"

    with (
        patch("app_support.file_channel.os.replace", side_effect=OSError("interrupted")),
        pytest.raises(OSError, match="could not replace"),
    ):
        write_whole(path, "the new one", attempts=1)

    assert list(tmp_path.iterdir()) == []


def test_two_publishers_of_one_file_never_share_a_temp_file_and_the_run_loop_hears_false_never_a_raise(tmp_path: Path):
    path = tmp_path / "status.txt"
    shared = path.with_suffix(".tmp")
    still_open = ExitStack()

    def hold_it_open_and_fail(src, _dst):
        still_open.enter_context(Path(src).open(encoding="utf-8"))  # noqa: SIM115
        raise OSError("held")

    with still_open, patch("app_support.file_channel.os.replace",
                           side_effect=hold_it_open_and_fail):
        landed = publish_whole(path, "one\n", attempts=1)

    assert landed is False
    assert not shared.exists(), "the temp file is named for the file, not for the writer"


def test_a_queue_a_writer_holds_this_instant_is_left_intact_for_the_next_drain(tmp_path: Path):
    path = tmp_path / "cmd.txt"
    path.write_text("NEXT", encoding="utf-8")

    with path.open(encoding="utf-8"):
        assert consume_command_file(path) == []

    assert consume_command_file(path) == ["NEXT"]

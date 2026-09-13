"""One contract test per file two repos meet at: its real writer against its
real reader, under the name both spell, through the calls both use.

Every value here is fabricated; the files are the family's, the contents are
not.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from app_support import state_files
from app_support.file_channel import (
    append_command,
    consume_command_file,
    publish_stamp,
    publish_whole,
    read_flag,
    read_key_values,
    read_paused_state,
    stamp_age,
    write_flag,
)

_NAMES = {name: value for name, value in vars(state_files).items() if name.isupper()}


def test_every_name_is_a_distinct_text_file_spelled_here_once():
    assert len(set(_NAMES.values())) == len(_NAMES)
    for value in _NAMES.values():
        assert value.endswith(".txt")
        assert value == value.lower()
        assert "/" not in value


class TestTheBrokersCommandFile:
    def test_a_verb_fun_time_queues_is_the_verb_the_broker_drains(self, tmp_path: Path):
        path = tmp_path / state_files.BROKER_CMD

        assert append_command(path, "park")

        assert consume_command_file(path) == ["PARK"]

    def test_two_verbs_between_ticks_are_both_heard_in_order(self, tmp_path: Path):
        """The defect the broker's own consumer had: it read the file and then
        truncated it, so a verb written into the gap was erased unread -- and
        two verbs read together came back as one word matching neither."""
        path = tmp_path / state_files.BROKER_CMD
        append_command(path, "park")
        append_command(path, "resume")

        assert consume_command_file(path) == ["PARK", "RESUME"]
        assert consume_command_file(path) == []


class TestTheBrokersHeartbeat:
    def test_what_the_broker_stamps_is_the_age_fun_time_reads(self, tmp_path: Path):
        path = tmp_path / state_files.BROKER_HEARTBEAT

        assert publish_stamp(path, 100.0)

        assert stamp_age(path, now=102.5) == 2.5

    def test_a_broker_that_never_ran_reads_as_never(self, tmp_path: Path):
        assert stamp_age(tmp_path / state_files.BROKER_HEARTBEAT, now=100.0) is None


@pytest.mark.parametrize("name", [state_files.OSR2_SERIAL_RX, state_files.OSR2_SERIAL_TX])
class TestTheDevicesLastWords:
    def test_what_the_broker_stamps_is_the_age_the_session_reads(self, tmp_path: Path, name: str):
        path = tmp_path / name
        publish_stamp(path, 100.0)

        assert stamp_age(path, now=115.0) == 15.0

    def test_a_device_that_never_spoke_reads_as_never(self, tmp_path: Path, name: str):
        assert stamp_age(tmp_path / name, now=100.0) is None


@pytest.mark.parametrize("name", [state_files.BROKER_MODE, state_files.GENAU_MODE])
class TestBrokerMode:
    """Under both names while the broker and Fun Time move from one to the other."""

    def test_what_the_broker_writes_is_what_fun_time_reads(self, tmp_path: Path, name: str):
        path = tmp_path / name

        write_flag(path, True)
        assert read_flag(path, default=False) is True
        write_flag(path, False)
        assert read_flag(path, default=False) is False

    def test_no_broker_yet_means_the_broker_is_not_in_auto(self, tmp_path: Path, name: str):
        assert read_flag(tmp_path / name, default=False) is False


class TestGenausChannel:
    def test_a_verb_fun_time_queues_is_the_verb_genau_drains(self, tmp_path: Path):
        path = tmp_path / state_files.GENAU_CMD
        append_command(path, "NEXT")

        assert consume_command_file(path) == ["NEXT"]

    def test_the_pause_fun_time_sets_is_the_pause_genau_obeys(self, tmp_path: Path):
        path = tmp_path / state_files.GENAU_PAUSED

        assert read_paused_state(path) is False
        write_flag(path, True)
        assert read_paused_state(path) is True

    def test_the_status_genau_publishes_is_the_record_fun_time_reads(self, tmp_path: Path):
        path = tmp_path / state_files.GENAU_STATUS

        assert publish_whole(path, "cruise=1\nlocked=0\nshape=sine\nclip=example.mp4\n")

        assert read_key_values(path) == {
            "cruise": "1", "locked": "0", "shape": "sine", "clip": "example.mp4"}

    def test_the_drive_genau_publishes_is_read_whole_by_main_player(self, tmp_path: Path):
        path = tmp_path / state_files.GENAU_DRIVE

        assert publish_whole(path, "speed=3\ndepth=40\n")

        assert path.read_text(encoding="utf-8") == "speed=3\ndepth=40\n"

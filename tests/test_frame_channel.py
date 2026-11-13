from __future__ import annotations

import pytest

from app_support.frame_channel import LOOK_AGAIN_AFTER_S, FrameLooks, FrameReader, FrameWriter


def _pixels(width: int, height: int, value: int) -> bytes:
    return bytes([value]) * (width * height * 4)


@pytest.fixture
def channel(tmp_path):
    writer = FrameWriter(tmp_path / "frame.bin", max_pixels=64)
    reader = FrameReader(tmp_path / "frame.bin")
    yield writer, reader
    reader.close()
    writer.close()


def test_a_frame_written_is_the_frame_read(channel):
    writer, reader = channel

    writer.write(3, 4, 2, _pixels(4, 2, 7))

    assert reader.latest(3) == (4, 2, _pixels(4, 2, 7))


def test_a_frame_drawn_for_an_earlier_opening_is_not_shown_for_this_one(channel):
    writer, reader = channel

    writer.write(2, 4, 2, _pixels(4, 2, 7))

    assert reader.latest(3) is None


def test_a_frame_already_read_is_not_read_again(channel):
    writer, reader = channel
    writer.write(3, 4, 2, _pixels(4, 2, 7))
    reader.latest(3)

    assert reader.latest(3) is None

    writer.write(3, 4, 2, _pixels(4, 2, 9))
    assert reader.latest(3) == (4, 2, _pixels(4, 2, 9))


def test_a_frame_still_being_written_is_left_for_the_next_look(channel):
    writer, reader = channel
    writer.write(3, 4, 2, _pixels(4, 2, 7))

    with writer.writing():
        assert reader.latest(3) is None


def test_a_reader_that_looks_before_anything_draws_sees_nothing_until_it_does(tmp_path):
    reader = FrameReader(tmp_path / "frame.bin")
    try:
        assert reader.latest(1) is None

        writer = FrameWriter(tmp_path / "frame.bin", max_pixels=64)
        try:
            assert reader.latest(1) is None
            writer.write(1, 2, 2, _pixels(2, 2, 5))
            assert reader.latest(1) == (2, 2, _pixels(2, 2, 5))
        finally:
            writer.close()
    finally:
        reader.close()


def test_a_frame_bigger_than_the_channel_is_refused(channel):
    writer, _reader = channel

    with pytest.raises(ValueError, match="a 10x10 frame does not fit this channel"):
        writer.write(1, 10, 10, _pixels(10, 10, 1))


def test_a_writer_counts_the_frames_it_has_written(channel):
    writer, _reader = channel

    writer.write(1, 2, 2, _pixels(2, 2, 5))
    writer.write(1, 2, 2, _pixels(2, 2, 6))

    assert writer.written == 2


def test_a_new_writer_starts_the_channel_empty(tmp_path):
    first = FrameWriter(tmp_path / "frame.bin", max_pixels=64)
    first.write(1, 2, 2, _pixels(2, 2, 5))
    first.close()

    second = FrameWriter(tmp_path / "frame.bin", max_pixels=64)
    reader = FrameReader(tmp_path / "frame.bin")
    try:
        assert reader.latest(1) is None
    finally:
        reader.close()
        second.close()


def test_a_window_nobody_asked_about_is_looked_at_again_only_after_a_while():
    looks = FrameLooks()

    assert [looks.due(now) for now in (0.0, LOOK_AGAIN_AFTER_S / 2,
                                       LOOK_AGAIN_AFTER_S)] == [True, False, True]


def test_a_window_asked_about_is_looked_at_at_once_and_only_once():
    looks = FrameLooks()
    looks.due(10.0)

    looks.ask()

    assert [looks.due(10.01), looks.due(10.02)] == [True, False]


def test_a_look_that_finds_the_same_pixels_sends_nothing_until_the_window_is_new():
    looks = FrameLooks()

    assert [looks.worth_sending(b"one"), looks.worth_sending(b"one"),
            looks.worth_sending(b"two")] == [True, False, True]
    looks.forget_what_was_sent()
    assert looks.worth_sending(b"two") is True

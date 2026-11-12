from __future__ import annotations

from app_support import video_kind


def test_a_video_of_ten_seconds_or_less_is_a_clip():
    assert video_kind.classify(genau=False, clip=False, duration_seconds=4.0) == video_kind.CLIP


def test_a_long_running_clip_is_full_length():
    assert video_kind.classify(genau=False, clip=False, duration_seconds=900.0) == video_kind.FULL_LENGTH


def test_an_unknown_running_time_reads_as_full_length():
    assert video_kind.classify(genau=False, clip=False, duration_seconds=None) == video_kind.FULL_LENGTH


def test_a_carved_excerpt_outranks_its_running_time():
    assert video_kind.classify(genau=False, clip=True, duration_seconds=4.0) == video_kind.CLIP


def test_a_genau_flick_outranks_everything_else():
    assert video_kind.classify(genau=True, clip=True, duration_seconds=900.0) == video_kind.GENAU_FLICK


def test_the_boundary_second_still_counts_as_a_clip():
    assert video_kind.classify(genau=False, clip=False,
                               duration_seconds=video_kind.CLIP_MAX_SECONDS) == video_kind.CLIP


def test_a_kind_known_without_measuring_is_a_genau_flick_or_an_excerpt_and_nothing_else():
    assert [video_kind.free_kind(genau=genau, clip=clip)
            for genau, clip in ((True, False), (False, True), (False, False))] == [
        video_kind.GENAU_FLICK, video_kind.CLIP, ""]


def test_the_kinds_are_the_three_words_a_record_can_hold():
    assert video_kind.TYPES == ("genau_flick", "excerpt", "full_length")

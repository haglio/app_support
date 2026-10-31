"""What a video's name and its record say it is, read the same by every app."""
from __future__ import annotations

from app_support.video_names import (
    UPSCALE_SUFFIX,
    clip_title,
    normalize_title,
    stable_title,
    strip_processing_suffixes,
    version_group_of,
)


class TestNormalizeTitle:
    def test_lowercases(self):
        assert normalize_title("Jane-Doe") == "jane doe"

    def test_strips_quality_and_upscaler_tokens(self):
        assert normalize_title("scene-three-upscale-mp4-1080p_60fps") == "scene three"
        assert normalize_title("Jane-Doe-&-John-Roe-old_iris2") == "jane doe & john roe"

    def test_strips_trailing_hash_tokens(self):
        assert normalize_title("redacted_540-EhWGJW62") == "redacted"
        assert normalize_title("Jane-Doe-&-John-Roe-ab12cd34-old_iris2") == "jane doe & john roe"

    def test_strips_a_trailing_hash_a_quality_tag_left_last(self):
        assert normalize_title("example_video-7c4d9e21_topaz") == "example video"

    def test_keeps_a_trailing_word_or_number_that_is_no_hash(self):
        assert normalize_title("Jane-Doe-compilation") == "jane doe compilation"
        assert normalize_title("Jane-Doe-scene-1") == "jane doe scene 1"


class TestStripProcessingSuffixes:
    def test_strips_single_model_suffix(self):
        assert strip_processing_suffixes("clip_iris2") == "clip"

    def test_strips_composite_model_chains(self):
        assert strip_processing_suffixes("clip_apo8_iris2") == "clip"
        assert strip_processing_suffixes("clip_apo8_prob4") == "clip"
        assert strip_processing_suffixes("clip_apo8_ghq5") == "clip"
        assert strip_processing_suffixes("clip_apo8_gcg5_topaz") == "clip"
        assert strip_processing_suffixes("clip_apo8_gcg5_topaz_cfr") == "clip"

    def test_plain_stem_unchanged(self):
        assert strip_processing_suffixes("Jane Doe - Beta Cut (1080)") == "Jane Doe - Beta Cut (1080)"

    def test_mid_name_tokens_are_not_suffixes(self):
        assert strip_processing_suffixes("clip_iris2_scene") == "clip_iris2_scene"

    def test_a_cfr_suffix_is_stripped_only_after_topaz(self):
        assert strip_processing_suffixes("clip_cfr") == "clip_cfr"

    def test_the_upscale_stages_suffix_is_one_of_the_suffixes_stripped(self):
        assert strip_processing_suffixes(f"clip{UPSCALE_SUFFIX}") == "clip"
        assert strip_processing_suffixes(f"clip{UPSCALE_SUFFIX}_cfr") == "clip"


class TestStableTitle:
    def test_a_processing_suffix_and_a_quality_tag_leave_the_same_title(self):
        assert stable_title("Ada-Roe-Beta-Cut_apo8_iris2") == stable_title("Ada-Roe-Beta-Cut-1080p_60fps")

    def test_a_trailing_hash_comes_off(self):
        assert stable_title("Jane-Doe_540-xq3k9v2w") == "jane doe"

    def test_two_scenes_of_one_performer_keep_different_titles(self):
        assert stable_title("Jane-Doe_540-xq3k9v2w") != stable_title("Jane Doe Beta Cut 4k 60fps")

    def test_a_name_of_nothing_but_tags_reduces_to_nothing(self):
        assert stable_title("1080p_60fps_topaz") == ""


class TestClipTitle:
    def test_is_the_performer_and_the_movie_its_clip_record_names(self):
        assert clip_title({"clip": {"performer": "Jane Doe", "source": "Alpha Study 3"}}) == (
            "Jane Doe - Alpha Study 3")

    def test_is_whichever_half_the_record_names(self):
        assert clip_title({"clip": {"performer": " Jane Doe ", "source": ""}}) == "Jane Doe"
        assert clip_title({"clip": {"source": "Alpha Study 3", "performer": None}}) == "Alpha Study 3"

    def test_is_nothing_for_a_video_no_clip_record_describes(self):
        assert clip_title({}) == ""
        assert clip_title({"clip": "Alpha Study 3"}) == ""


def test_a_videos_version_family_is_the_group_evolver_recorded():
    assert version_group_of({"version": {"group": "y", "processed": True}}) == "y"
    assert version_group_of({"clip": {"compilation": "Vol6"}}) == ""
    assert version_group_of({"version": "y"}) == ""

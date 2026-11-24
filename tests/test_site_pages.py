from __future__ import annotations

import json
from urllib.parse import unquote

from app_support.local_time import when_words
from app_support.site_pages import FILL_SCRIPT, fill_script, page_address, settings_for_the_page

VIDEO_PAGE = "https://example.com/video"
IMAGE_PAGE = "https://example.com/create"

A_VIDEO_FROM_AN_IMAGE = {
    "video": {
        "prompt": "VIDEO PROMPT",
        "model": "Made Up",
        "action": "Alpha Beta",
        "resolution": "544x816",
        "aspect_ratio": "2:3",
        "quality": "720p",
        "seed": "3443370201",
        "created": "2025-12-28",
    },
    "source_image": {
        "positive_prompt": "POSITIVE",
        "negative_prompt": "NEGATIVE",
        "model": "Made Up",
        "resolution": "1280x1920",
        "aspect_ratio": "2:3",
        "quality": "Best",
        "seed": "2559368667",
        "created": "2025-12-28",
        "style": "Default",
        "creativity": "7",
    },
}

A_VIDEO_ALONE = {
    "video": {
        "prompt": "JUST A VIDEO",
        "model": "Video v3",
        "action": "Side Epsilon",
        "resolution": "1280x720",
        "aspect_ratio": "16:9",
        "quality": "720p",
        "seed": "4029423637",
        "created": "2026-03-13",
    }
}


def _packed_into(address: str) -> dict:
    return json.loads(unquote(address.split("#ft=", 1)[1]))


def test_an_image_is_asked_for_with_both_its_prompts_and_its_videos_settings_for_after():
    settings = settings_for_the_page(A_VIDEO_FROM_AN_IMAGE)

    assert settings["kind"] == "image"
    assert settings["positive"] == "POSITIVE"
    assert settings["negative"] == "NEGATIVE"
    assert settings["video_prompt"] == "VIDEO PROMPT"
    assert ["Quality", "Best"] in settings["settings"]
    assert ["Style", "Default"] in settings["settings"]
    assert ["Model", "Made Up"] in settings["settings"]
    assert ["Action", "Alpha Beta"] in settings["video_settings"]


def test_a_video_alone_is_asked_for_as_a_video_with_no_negative_prompt():
    settings = settings_for_the_page(A_VIDEO_ALONE)

    assert settings["kind"] == "video"
    assert settings["positive"] == "JUST A VIDEO"
    assert settings["negative"] == ""
    assert settings["video_prompt"] == ""
    assert ["Action", "Side Epsilon"] in settings["settings"]


def test_when_a_video_was_made_reads_in_local_time_with_its_day():
    record = {"video": {"prompt": "p", "created": "2026-03-13 20:15:00"}}

    assert ["Created", when_words("2026-03-13 20:15:00")] in settings_for_the_page(record)["settings"]


def test_a_setting_the_record_leaves_empty_is_left_out():
    record = {"video": {"prompt": "p", "model": "", "seed": "123"}}

    assert [name for name, _ in settings_for_the_page(record)["settings"]] == ["Seed"]


def test_an_images_address_is_the_image_page_with_its_settings_packed_after_it():
    address = page_address(A_VIDEO_FROM_AN_IMAGE, video_page=VIDEO_PAGE, image_page=IMAGE_PAGE)

    assert address.startswith(IMAGE_PAGE + "#ft=")
    assert _packed_into(address) == settings_for_the_page(A_VIDEO_FROM_AN_IMAGE)


def test_a_videos_address_is_the_video_page():
    address = page_address(A_VIDEO_ALONE, video_page=VIDEO_PAGE, image_page=IMAGE_PAGE)

    assert address.startswith(VIDEO_PAGE + "#ft=")
    assert _packed_into(address)["kind"] == "video"


def test_an_address_that_asks_the_page_to_submit_says_so():
    address = page_address(A_VIDEO_FROM_AN_IMAGE, video_page=VIDEO_PAGE, image_page=IMAGE_PAGE,
                           submit=True)

    assert _packed_into(address)["submit"] is True


def test_an_address_that_only_fills_the_form_packs_no_word_of_submitting():
    address = page_address(A_VIDEO_ALONE, video_page=VIDEO_PAGE, image_page=IMAGE_PAGE)

    assert "submit" not in _packed_into(address)


def test_the_fill_script_is_found_in_the_first_checkout_that_holds_one(tmp_path):
    without, holding = tmp_path / "without", tmp_path / "holding"
    (holding / FILL_SCRIPT).parent.mkdir(parents=True)
    (holding / FILL_SCRIPT).write_text("// made up", encoding="utf-8")

    assert fill_script([without, holding]) == holding / FILL_SCRIPT


def test_no_fill_script_is_found_where_no_checkout_holds_one(tmp_path):
    assert fill_script([tmp_path]) is None

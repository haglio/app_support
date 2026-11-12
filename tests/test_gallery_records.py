from __future__ import annotations

import json
from pathlib import PurePosixPath

from app_support.gallery_records import (
    RECORD_COLUMNS,
    GalleryReading,
    aspect_ratio,
    model_label,
    size_labels,
)

_FRAME = "frame-one.png"
_WORDS_VIDEO = {"prompt": "a lighthouse in words", "model": "Motion W", "seed": "7"}


def _outside(prompt_id: str, file: str, *, params: dict, **fields) -> dict:
    return {"prompt_id": prompt_id, "source": "outside", "params_json": json.dumps(params),
            "output_files": json.dumps([{"filename": PurePosixPath(file).name,
                                         "library_path": file}]), **fields}


def _frame(prompt_id: str, *files: str, source="starting_frame", **fields) -> dict:
    return {"prompt_id": prompt_id, "source": source, "params_json": "{}",
            "output_files": json.dumps([{"filename": name} for name in files]), **fields}


def _made_here(prompt_id: str, filename: str, *, params: dict | None = None, **fields) -> dict:
    return {"prompt_id": prompt_id, "source": "generated", "params_json": json.dumps(params or {}),
            "output_files": json.dumps([{"filename": filename, "subfolder": "video"}]), **fields}


def _record(rows: list[dict], video: str, **where) -> dict:
    reading = GalleryReading(rows)
    return reading.record_of(reading.row_of(video), **where)


_KINO = "L:/library/videos/videos/kino/2D/AI/portrait/a-site"


def test_a_sites_video_carries_what_its_row_and_the_image_it_was_made_from_say():
    rows = [_frame("image-1", "image one.jpg", source="outside",
                   params_json=json.dumps({"positive_prompt": "a quiet shore", "seed": "22",
                                           "model": "Image Model"})),
            _outside("v1", f"{_KINO}/scene one.mp4",
                     params={"positive_prompt": "a slow walk", "model": "Video Model",
                             "resolution": "720p", "seed": "11", "input_image": "image one.jpg"},
                     recipe_category="alpha", combined_labels=json.dumps(["alpha", "beta"]))]

    record = _record(rows, f"{_KINO}/scene one.mp4")

    assert (record["video"], record["source_image"]) == (
        {"prompt": "a slow walk", "model": "Video Model", "resolution": "720p", "seed": "11",
         "action": "alpha", "labels": ["alpha", "beta"], "orientation": "portrait",
         "type": "full_length"},
        {"positive_prompt": "a quiet shore", "seed": "22", "model": "Image Model"})


def test_a_record_carries_the_star_the_watch_counts_and_their_weight():
    rows = [_outside("v1", f"{_KINO}/scene one.mp4", params={}, starred=1, watch_completions=3,
                     watch_skips=0, watch_locks=0)]

    record = _record(rows, f"{_KINO}/scene one.mp4")

    assert (record["favorite"], record["watch"]) == (
        True, {"completions": 3, "skips": 0, "locks": 0, "weight": 2.0})


def test_a_video_made_from_words_alone_has_no_source_image():
    rows = [_frame("frame-1", "scene one.jpg"),
            _outside("v1", f"{_KINO}/scene one.mp4", params={"input_image": "scene one.jpg"})]

    assert "source_image" not in _record(rows, f"{_KINO}/scene one.mp4")


def test_a_video_made_from_a_text_to_video_videos_frame_names_the_video_it_was_taken_from():
    rows = [_frame("frame-1", _FRAME, positive_prompt="the words of the frame"),
            _outside("words-1", f"{_KINO}/words one.mp4",
                     params={"positive_prompt": "a lighthouse in words", "model": "Motion W",
                             "seed": "7", "input_image": _FRAME}),
            _made_here("made-1", "wan22_i2v_00001_.mp4", params={"input_image": _FRAME})]

    record = _record(rows, f"{_KINO}/wan22_i2v_00001__topaz.mp4")

    assert record["source_image"]["positive_prompt"] == "the words of the frame"
    assert {key: record["source_image"]["frame_of_video"][key] for key in _WORDS_VIDEO} == (
        _WORDS_VIDEO)


def test_a_video_made_from_an_image_names_no_video_it_was_taken_from():
    rows = [_frame("image-1", _FRAME, source="outside", positive_prompt="an image"),
            _outside("words-1", f"{_KINO}/words one.mp4",
                     params={"positive_prompt": "words", "input_image": _FRAME}),
            _made_here("made-1", "wan22_i2v_00001_.mp4", params={"input_image": _FRAME})]

    assert "frame_of_video" not in _record(rows, f"{_KINO}/wan22_i2v_00001__topaz.mp4")[
        "source_image"]


def test_a_videos_orientation_is_the_shape_its_row_holds_or_else_the_folder_it_is_filed_in():
    rows = [_outside("v1", f"{_KINO}/scene one.mp4", params={}, shape="landscape"),
            _outside("v2", f"{_KINO}/scene two.mp4", params={}),
            _outside("v3", "L:/library/elsewhere/scene three.mp4", params={})]

    assert [_record(rows, place)["video"].get("orientation") for place in (
        f"{_KINO}/scene one.mp4", f"{_KINO}/scene two.mp4", "L:/library/elsewhere/scene three.mp4")
    ] == ["landscape", "portrait", None]


def test_a_videos_type_comes_from_where_it_plays_and_how_long_its_row_says_it_runs():
    rows = [_outside("v1", f"{_KINO}/scene one.mp4", params={}, video_seconds=4.0),
            _outside("v2", f"{_KINO}/scene two.mp4", params={}, video_seconds=400.0)]

    assert [_record(rows, f"{_KINO}/{name}")["video"]["type"]
            for name in ("scene one.mp4", "scene two.mp4")] == ["excerpt", "full_length"]
    assert _record(rows, f"{_KINO}/scene two.mp4", genau=True)["video"]["type"] == "genau_flick"
    assert _record(rows, f"{_KINO}/scene two.mp4", seconds=2.0)["video"]["type"] == "excerpt"


def test_a_flick_turned_over_in_genau_says_so_and_one_that_was_not_says_nothing():
    rows = [_outside("v1", f"{_KINO}/scene one.mp4", params={}, genau_flipped=1),
            _outside("v2", f"{_KINO}/scene two.mp4", params={})]

    assert [_record(rows, f"{_KINO}/{name}").get("genau")
            for name in ("scene one.mp4", "scene two.mp4")] == [{"flipped": True}, None]


def test_an_action_reads_the_same_whether_the_row_came_raw_or_through_origenerator():
    raw = _outside("v1", f"{_KINO}/scene one.mp4", params={}, recipe_category="alpha")
    read = {**{key: value for key, value in raw.items() if key != "recipe_category"},
            "action": "alpha"}

    assert [_record([row], f"{_KINO}/scene one.mp4")["video"]["action"] for row in (raw, read)] == [
        "alpha", "alpha"]


def test_a_video_no_row_holds_has_no_row():
    assert GalleryReading([]).row_of(f"{_KINO}/scene one.mp4") is None


def test_the_columns_a_reader_must_ask_for_are_every_one_the_builder_reads():
    assert set(RECORD_COLUMNS) == {
        "prompt_id", "source", "params_json", "output_files", "evolver_upscale",
        "recipe_category", "combined_labels", "starred", "watch_completions", "watch_skips",
        "watch_locks", "shape", "video_seconds", "video_resolution", "video_aspect_ratio",
        "genau_flipped", "positive_prompt",
        "negative_prompt", "seed"}


def test_a_model_label_prefers_unet_high_and_strips_the_extension():
    assert model_label({"unet_high": "wan_high.gguf", "unet_low": "wan_low.gguf"}) == "wan_high"


def test_a_model_label_reads_a_flux_unet():
    assert model_label({"unet": "flux1-dev.safetensors"}) == "flux1-dev"


def test_a_model_label_reads_a_checkpoint_in_a_folder():
    assert model_label({"checkpoint": "sub\\reapony_v80.safetensors"}) == "reapony_v80"


def test_a_model_label_is_empty_with_no_model_key():
    assert model_label({"steps": 8}) == ""


def test_a_video_made_here_and_the_image_it_was_made_from_carry_their_models():
    image = _made_here("img-1", "wan22_t2i_00005_.png", params={"checkpoint": "reapony_v80.safetensors"},
                       positive_prompt="portrait of a woman", negative_prompt="blurry", seed=7)
    video = _made_here("vid-1", "wan22_i2v_00009_.mp4", positive_prompt="she turns around", seed=42,
                       params={"unet_high": "wan_high.gguf",
                               "input_image": "wan22_t2i_00005_.png [output]"})

    record = _record([image, video], f"{_KINO}/wan22_i2v_00009__topaz.mp4")

    assert {key: record["video"][key] for key in ("prompt", "model", "seed")} == {
        "prompt": "she turns around", "model": "wan_high", "seed": "42"}
    assert record["source_image"] == {"positive_prompt": "portrait of a woman",
                                      "negative_prompt": "blurry", "model": "reapony_v80",
                                      "seed": "7"}


def test_a_video_made_here_with_nothing_recorded_has_no_field_written_empty():
    record = _record([_made_here("vid-1", "wan22_i2v_00001_.mp4")],
                     f"{_KINO}/wan22_i2v_00001__topaz.mp4")

    assert set(record["video"]) == {"type"}


def test_a_wide_size_reads_as_sixteen_by_nine():
    assert aspect_ratio(832, 480) == "16:9"


def test_a_tall_size_reads_as_nine_by_sixteen():
    assert aspect_ratio(480, 832) == "9:16"


def test_a_square_size_reads_as_one_by_one():
    assert aspect_ratio(624, 624) == "1:1"


def test_an_uncommon_ratio_is_reduced():
    assert aspect_ratio(1000, 300) == "10:3"


def test_a_size_with_no_extent_has_no_ratio():
    assert aspect_ratio(0, 480) == ""


def test_a_size_is_labeled_as_the_sidecars_spelled_it():
    assert size_labels(832, 480) == {"video_resolution": "832x480", "video_aspect_ratio": "16:9"}


def test_a_video_made_here_carries_the_size_its_row_keeps():
    video = _made_here("vid-1", "wan22_i2v_00001_.mp4", video_resolution="832x480",
                       video_aspect_ratio="16:9")

    shown = _record([video], f"{_KINO}/wan22_i2v_00001__topaz.mp4")["video"]

    assert (shown["resolution"], shown["aspect_ratio"]) == ("832x480", "16:9")

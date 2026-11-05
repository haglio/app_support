from __future__ import annotations

import json
import random

from app_support.watch_weights import (
    passes_inclusion,
    recorded_weight,
    weight_of,
    weighted_shuffle,
)


def test_weighted_shuffle_front_loads_heavy_items():
    rng = random.Random(7)
    weights = {"heavy.mp4": 8.0, "light.mp4": 0.125}

    heavy_first = sum(
        weighted_shuffle(["light.mp4", "heavy.mp4"], weights.get, rng)[0] == "heavy.mp4"
        for _ in range(200)
    )

    assert heavy_first > 150


def test_weighted_shuffle_preserves_items_and_handles_empty():
    rng = random.Random(1)
    paths = [f"clip{i}.mp4" for i in range(10)]

    result = weighted_shuffle(paths, lambda _p: 1.0, rng)

    assert sorted(result) == sorted(paths)
    assert weighted_shuffle([], lambda _p: 1.0, rng) == []


def test_passes_inclusion_only_drops_below_neutral_weight():
    rng = random.Random(3)
    assert all(passes_inclusion(1.0, rng) for _ in range(100))
    assert all(passes_inclusion(8.0, rng) for _ in range(100))
    kept = sum(passes_inclusion(0.5, rng) for _ in range(200))
    assert 60 < kept < 140


def test_a_records_weight_is_the_one_stamped_on_it_and_one_where_none_is():
    assert weight_of({"watch": {"completions": 3, "skips": 0, "locks": 0, "weight": 2.0}}) == 2.0
    assert weight_of({"video": {"type": "short"}}) == 1.0
    assert weight_of({"watch": "eight"}) == 1.0
    assert weight_of({"watch": {"weight": "heavy"}}) == 1.0


def _library(tmp_path):
    return tmp_path / "videos" / "videos", tmp_path / "videos" / "metadata"


def test_a_videos_weight_is_read_from_the_record_filed_for_it(tmp_path):
    videos, records = _library(tmp_path)
    record = records / "portrait" / "scene one.json"
    record.parent.mkdir(parents=True)
    record.write_text(json.dumps({"watch": {"weight": 4.0}}), encoding="utf-8")

    assert recorded_weight(videos / "portrait" / "scene one.mp4", records) == 4.0


def test_a_video_with_no_record_or_a_broken_one_or_outside_the_library_weighs_one(tmp_path):
    videos, records = _library(tmp_path)
    broken = records / "portrait" / "scene two.json"
    broken.parent.mkdir(parents=True)
    broken.write_text('{"watch": {"weight"', encoding="utf-8")

    assert recorded_weight(videos / "portrait" / "scene one.mp4", records) == 1.0
    assert recorded_weight(videos / "portrait" / "scene two.mp4", records) == 1.0
    assert recorded_weight(tmp_path / "elsewhere" / "scene one.mp4", records) == 1.0
    assert recorded_weight(videos / "portrait" / "scene one.mp4", None) == 1.0

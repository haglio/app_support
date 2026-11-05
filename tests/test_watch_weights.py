from __future__ import annotations

import random

from app_support.watch_weights import passes_inclusion, weight_of, weighted_shuffle


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

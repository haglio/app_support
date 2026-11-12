from __future__ import annotations

import random

from app_support.watch_weights import (
    Staying,
    add_counts,
    dealt_by_weight,
    newest_of_each_group,
    passes_inclusion,
    weight_for,
    weight_of,
    weighted_shuffle,
)


def test_a_video_nothing_has_watched_weighs_one():
    assert weight_for(None) == 1.0
    assert weight_for({}) == 1.0


def test_three_completions_double_the_weight_and_three_skips_halve_it():
    assert weight_for({"completions": 3}) == 2.0
    assert weight_for({"skips": 3}) == 0.5


def test_one_lock_outweighs_one_completion():
    assert weight_for({"locks": 1}) > weight_for({"completions": 1})


def test_the_weight_is_clamped_to_an_eighth_and_eightfold():
    assert weight_for({"completions": 100, "locks": 50}) == 8.0
    assert weight_for({"skips": 100}) == 0.125


def test_counts_add_up_field_by_field_across_sources_reading_absent_as_zero():
    assert add_counts({"completions": 2, "locks": 1}, None, {"completions": 1, "skips": 4}) == {
        "completions": 3, "skips": 4, "locks": 1}


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


_GROUPS = {"alpha one": "alpha", "alpha two": "alpha", "alpha three": "alpha",
           "beta": "beta", "gamma": None}


def _deal(items, weights=None, *, seed, **staying):
    weights = weights or {}
    return dealt_by_weight(items, weight_of=lambda item: weights.get(item, 1.0),
                           group_of=_GROUPS.get, rng=random.Random(seed),
                           staying=Staying(**staying))


def test_a_deal_by_weight_keeps_one_of_each_group_and_every_item_with_none():
    group = {"alpha one", "alpha two", "alpha three"}
    picked = set()
    for seed in range(30):
        deal = _deal(list(_GROUPS), seed=seed)
        assert len(group.intersection(deal)) == 1
        assert {"beta", "gamma"} <= set(deal)
        assert len(deal) == 3
        picked |= group.intersection(deal)

    assert picked == group


def test_the_one_a_group_keeps_follows_the_weights():
    weights = {"alpha one": 8.0, "alpha two": 0.125, "alpha three": 0.125}

    loved = sum("alpha one" in _deal(list(_GROUPS), weights, seed=seed) for seed in range(40))

    assert loved >= 36


def test_an_item_weighing_an_eighth_sits_most_deals_out():
    appearances = sum("beta" in _deal(list(_GROUPS), {"beta": 0.125}, seed=seed)
                      for seed in range(40))

    assert appearances < 15


def test_what_must_stay_stays_whatever_it_weighs_and_holds_its_group():
    weights = dict.fromkeys(_GROUPS, 0.0)

    for seed in range(10):
        deal = _deal(list(_GROUPS), weights, seed=seed, kept=lambda item: item == "alpha two")
        assert deal == ["alpha two"]


def test_a_deal_asked_never_to_come_back_empty_keeps_one_of_each_group_when_all_sit_out():
    weights = dict.fromkeys(_GROUPS, 0.0)

    assert _deal(list(_GROUPS), weights, seed=1) == []
    deal = _deal(list(_GROUPS), weights, seed=1, never_empty=True)

    assert sorted(deal, key=str)[1:] == ["beta", "gamma"]
    assert len(deal) == 3


def test_newest_first_keeps_the_newest_of_each_group_in_its_place_and_every_item_with_none():
    newest_first = ["alpha two", "beta", "alpha one", "gamma", "alpha three"]

    assert newest_of_each_group(newest_first, _GROUPS.get) == ["alpha two", "beta", "gamma"]


def test_newest_first_keeps_what_must_stay_in_place_of_its_groups_newest():
    newest_first = ["alpha two", "beta", "alpha one", "gamma"]

    kept = newest_of_each_group(newest_first, _GROUPS.get, kept=lambda item: item == "alpha one")

    assert kept == ["alpha one", "beta", "gamma"]


def test_a_caller_says_which_of_a_group_is_its_newest():
    newest_first = ["alpha two", "beta", "alpha one"]

    kept = newest_of_each_group(newest_first, _GROUPS.get, newest=min)

    assert kept == ["alpha one", "beta"]

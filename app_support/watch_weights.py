from __future__ import annotations

import math
import random
from collections.abc import Callable, Hashable, Iterable
from dataclasses import dataclass

WATCH_BLOCK = "watch"
WEIGHT_KEY = "weight"
NEUTRAL_WEIGHT = 1.0


def weight_of(record: dict) -> float:
    block = record.get(WATCH_BLOCK)
    if not isinstance(block, dict):
        return NEUTRAL_WEIGHT
    try:
        return float(block.get(WEIGHT_KEY, NEUTRAL_WEIGHT))
    except (TypeError, ValueError):
        return NEUTRAL_WEIGHT


def weighted_shuffle[T](
    items: Iterable[T],
    weight_of_item: Callable[[T], float | None],
    rng: random.Random,
) -> list[T]:
    def sort_key(item: T) -> float:
        weight = weight_of_item(item) or NEUTRAL_WEIGHT
        u = max(rng.random(), 1e-12)
        return -math.log(u) / weight

    return sorted(items, key=sort_key)


def passes_inclusion(weight: float, rng: random.Random) -> bool:
    return weight >= NEUTRAL_WEIGHT or rng.random() < weight


def _nothing_kept(_item: object) -> bool:
    return False


def _first[T](group: list[T]) -> T:
    return group[0]


@dataclass(frozen=True)
class Staying[T]:
    kept: Callable[[T], bool] = _nothing_kept
    never_empty: bool = False


NOTHING_STAYS: Staying = Staying()


def dealt_by_weight[T](
    items: Iterable[T],
    *,
    weight_of: Callable[[T], float],
    group_of: Callable[[T], Hashable | None],
    rng: random.Random,
    staying: Staying[T] = NOTHING_STAYS,
) -> list[T]:
    items = list(items)
    survivors = [item for item in items
                 if staying.kept(item) or passes_inclusion(weight_of(item), rng)]
    if staying.never_empty and not survivors:
        survivors = items

    def pick(group: list[T]) -> T:
        weights = [weight_of(item) or NEUTRAL_WEIGHT for item in group]
        return rng.choices(group, weights=weights, k=1)[0]

    picks = _one_per_group(survivors, group_of, pick, staying.kept)
    return weighted_shuffle(picks, weight_of, rng)


def newest_of_each_group[T](
    newest_first: Iterable[T],
    group_of: Callable[[T], Hashable | None],
    *,
    newest: Callable[[list[T]], T] = _first,
    kept: Callable[[T], bool] = _nothing_kept,
) -> list[T]:
    return _one_per_group(list(newest_first), group_of, newest, kept)


def _one_per_group[T](
    items: list[T],
    group_of: Callable[[T], Hashable | None],
    pick: Callable[[list[T]], T],
    kept: Callable[[T], bool],
) -> list[T]:
    keyed = [(item, group_of(item)) for item in items]
    groups: dict[Hashable, list[T]] = {}
    for item, key in keyed:
        if key is not None:
            groups.setdefault(key, []).append(item)
    picks: list[T] = []
    for item, key in keyed:
        if key is None:
            picks.append(item)
        elif key in groups:
            group = groups.pop(key)
            staying = [one for one in group if kept(one)]
            picks.extend(staying or [pick(group)])
    return picks


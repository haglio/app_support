from __future__ import annotations

import math
import random
from collections.abc import Callable, Iterable

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


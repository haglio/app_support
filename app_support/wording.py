"""How a list of things reads in a sentence.

Standard library only.
"""
from __future__ import annotations

from collections.abc import Sequence


def listed(things: Sequence[str]) -> str:
    return things[0] if len(things) == 1 else f"{', '.join(things[:-1])} and {things[-1]}"

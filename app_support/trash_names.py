from __future__ import annotations

import re
from itertools import chain, count
from pathlib import Path

_NUMBERED = "__dup"
_NUMBER_ENDING = re.compile(rf"{_NUMBERED}\d+$")


def spot_in_trash(trash_folder: Path, name: str) -> Path:
    stem, suffix = Path(name).stem, Path(name).suffix
    numbered = (trash_folder / f"{stem}{_NUMBERED}{number}{suffix}" for number in count(1))
    return next(spot for spot in chain([trash_folder / name], numbered) if not spot.exists())


def name_before_trash(name: str) -> str:
    return f"{_NUMBER_ENDING.sub('', Path(name).stem)}{Path(name).suffix}"

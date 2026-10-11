"""Genau's folders in the library, where Fun Time, Evolver and Genaumacher meet.

The folder holding Genau's flicks is named in the library's own vocabulary,
which no tracked file may spell, so it is found by its shape.
"""
from __future__ import annotations

from pathlib import Path

WEIRD_PILE = "weird"


def flicks_folder(genau: Path) -> Path | None:
    if not genau.is_dir():
        return None
    fitting = [folder for folder in genau.iterdir()
               if folder.is_dir() and folder.name != WEIRD_PILE and (folder / "2D").is_dir()]
    return fitting[0] if len(fitting) == 1 else None

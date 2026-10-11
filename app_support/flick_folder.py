"""The folder Genau's flicks live in, laid out the same for every app that meets it.

What the folder is called is the library's own vocabulary, which no tracked file
may spell, so it is found by its shape rather than its name.
"""
from __future__ import annotations

from pathlib import Path


def flat_flicks_in(flicks_folder: Path) -> Path:
    return flicks_folder / "2D"


def vr_flicks_in(flicks_folder: Path) -> Path:
    return flicks_folder / "VR"


def weird_pile_in(genau: Path) -> Path:
    return genau / "weird"


def weird_dir_for_flicks_folder(folder: Path) -> Path:
    return weird_pile_in(folder.parent)


def flicks_folder_in(genau: Path) -> Path | None:
    if not genau.is_dir():
        return None
    fitting = [folder for folder in genau.iterdir()
               if folder.is_dir() and folder != weird_dir_for_flicks_folder(folder)
               and flat_flicks_in(folder).is_dir()]
    return fitting[0] if len(fitting) == 1 else None

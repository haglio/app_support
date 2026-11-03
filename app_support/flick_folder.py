from __future__ import annotations

from pathlib import Path


def flat_flicks_in(flicks_folder: Path) -> Path:
    return flicks_folder / "2D"


def vr_flicks_in(flicks_folder: Path) -> Path:
    return flicks_folder / "VR"


def trash_folder_in(genau: Path) -> Path:
    return genau / "trash"


def audio_in(genau: Path) -> Path:
    return genau / "audio"


def trash_folder_beside(flicks_folder: Path) -> Path:
    return trash_folder_in(flicks_folder.parent)


def flicks_folder_in(genau: Path) -> Path | None:
    if not genau.is_dir():
        return None
    fitting = [folder for folder in genau.iterdir()
               if folder.is_dir() and folder != trash_folder_beside(folder)
               and flat_flicks_in(folder).is_dir()]
    return fitting[0] if len(fitting) == 1 else None

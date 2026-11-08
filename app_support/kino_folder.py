from __future__ import annotations

from pathlib import Path

from app_support import flick_folder, haglio_settings
from app_support.video_names import UPSCALE_SUFFIX

trash_folder_in = flick_folder.trash_folder_in


def kino_dir() -> Path:
    return Path(haglio_settings.value("kino_dir"))


def upscales_in(kino: Path) -> Path:
    return kino / "2D" / "AI"


def upscale_in(kino: Path, orientation: str, source: str, sorted_stem: str) -> Path:
    return upscales_in(kino) / orientation / source / f"{sorted_stem}{UPSCALE_SUFFIX}.mp4"


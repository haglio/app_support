from __future__ import annotations

from pathlib import Path, PurePath

from app_support import flick_folder, haglio_settings
from app_support.video_names import UPSCALE_SUFFIX

trash_folder_in = flick_folder.trash_folder_in


def kino_dir() -> Path:
    return Path(haglio_settings.value("kino_dir"))


AI_FOLDER = ("2D", "AI")


def upscales_in(kino: Path) -> Path:
    return kino.joinpath(*AI_FOLDER)


def is_ai_video(path: PurePath) -> bool:
    parts = PurePath(path).parent.parts
    return any(parts[at:at + len(AI_FOLDER)] == AI_FOLDER for at in range(len(parts)))


def upscale_in(kino: Path, orientation: str, source: str, sorted_stem: str) -> Path:
    return upscales_in(kino) / orientation / source / f"{sorted_stem}{UPSCALE_SUFFIX}.mp4"


from __future__ import annotations

from pathlib import Path

from app_support import flick_folder, haglio_settings
from app_support.video_names import UPSCALE_SUFFIX

trash_folder_in = flick_folder.trash_folder_in

RETIRED_OUTBOX = ("videos", "videos", "2D", "AI", "2_outbox")
_RETIRED_UPSCALES = "upscaled_by_orientation"
_RETIRED_TRASH = "trash"


def kino_dir() -> Path:
    return Path(haglio_settings.value("kino_dir"))


def upscales_in(kino: Path) -> Path:
    return kino / "2D" / "AI"


def upscale_in(kino: Path, orientation: str, source: str, sorted_stem: str) -> Path:
    return upscales_in(kino) / orientation / source / f"{sorted_stem}{UPSCALE_SUFFIX}.mp4"


def retired_outbox_in(library_root: Path) -> Path:
    return library_root.joinpath(*RETIRED_OUTBOX)


def where_it_went(path: Path, library_root: Path, kino: Path) -> Path | None:
    try:
        held_in, *inside = Path(path).relative_to(retired_outbox_in(library_root)).parts
    except ValueError:
        return None
    if not inside:
        return None
    if held_in == _RETIRED_UPSCALES:
        return upscales_in(kino).joinpath(*inside)
    if held_in == _RETIRED_TRASH:
        return trash_folder_in(kino).joinpath(*inside)
    return None

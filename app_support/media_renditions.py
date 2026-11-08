from __future__ import annotations

from pathlib import Path

from app_support import kino_folder
from app_support.video_names import UPSCALE_SUFFIX

_ORIGINAL_ROOT = "1_sorted"
_RETIRED_UPSCALES = ("2_outbox", "upscaled_by_orientation")


def _upscale_folders(media_root: Path) -> tuple[Path, Path]:
    return kino_folder.upscales_in(kino_folder.kino_dir()), media_root.joinpath(*_RETIRED_UPSCALES)


def _filed_under(video: Path, media_root: Path) -> tuple[str, str] | None:
    for folder in _upscale_folders(media_root):
        try:
            orientation, source, _name = video.relative_to(folder).parts
        except ValueError:
            continue
        return orientation, source
    return None


def original_rendition(video_path: str | Path, media_root: str | Path | None) -> str:
    if not video_path or media_root is None:
        return ""
    video = Path(video_path)
    filed = _filed_under(video, Path(media_root))
    if filed is None:
        return ""
    orientation, source = filed
    stem = video.stem.removesuffix(UPSCALE_SUFFIX)
    original = Path(media_root) / _ORIGINAL_ROOT / source / orientation / (stem + video.suffix)
    return str(original) if original.is_file() else ""


def renditions(video_path: str | Path, media_root: str | Path | None) -> list[str]:
    original = original_rendition(video_path, media_root)
    return [str(video_path), original] if original else []

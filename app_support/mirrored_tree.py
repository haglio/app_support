from __future__ import annotations

import os
from collections.abc import Callable, Iterable, Sequence
from pathlib import Path

from app_support.json_store import read_json

LIBRARY_DIR_NAME = "videos"


def library_roots_beside(mirror_root: Path) -> tuple[Path, Path]:
    mirror_root = Path(mirror_root)
    return (mirror_root.parent / LIBRARY_DIR_NAME, mirror_root.parent)


def mirrored_path(
    source: Path,
    *,
    roots: Sequence[Path],
    mirror_root: Path,
    suffix: str,
) -> Path | None:
    for root in roots:
        for spelling in _SPELLINGS_CHEAPEST_FIRST_THE_DISK_LAST:
            try:
                relative = spelling(source).relative_to(spelling(root))
            except ValueError:
                continue
            return (Path(mirror_root) / relative).with_suffix(suffix)
    return None


def mirrored_source(
    counterpart: Path,
    *,
    roots: Sequence[Path],
    mirror_root: Path,
    suffixes: Iterable[str],
) -> Path | None:
    relative, suffixes = Path(counterpart).relative_to(mirror_root), tuple(suffixes)
    for root in roots:
        for suffix in suffixes:
            source = (Path(root) / relative).with_suffix(suffix)
            if source.is_file():
                return source
    return None


def _as_spelled(path: Path) -> Path:
    return Path(os.path.abspath(path))


def _as_folded(path: Path) -> Path:
    """Case folded: CPython's `relative_to` compares text, though Windows treats a root with a capital as the same place."""
    return Path(str(_as_spelled(path)).lower())


def _as_the_disk_has_it(path: Path) -> Path:
    """Follows junctions and links; on a Windows drive pCloud is syncing that can block for minutes."""
    try:
        return Path(path).resolve()
    except OSError:
        return Path(path)


_SPELLINGS_CHEAPEST_FIRST_THE_DISK_LAST: tuple[Callable[[Path], Path], ...] = (
    _as_spelled,
    _as_folded,
    _as_the_disk_has_it,
)


def record_path(video: Path, records_folder: Path, *, more_roots: Sequence[Path] = ()) -> Path | None:
    return mirrored_path(video, roots=(*library_roots_beside(records_folder), *more_roots),
                         mirror_root=records_folder, suffix=".json")


def filed_record(video: Path, records_folder: Path | None) -> dict:
    record = record_path(video, records_folder) if records_folder is not None else None
    if record is None:
        return {}
    try:
        filed = read_json(record)
    except (OSError, ValueError):
        return {}
    return filed if isinstance(filed, dict) else {}

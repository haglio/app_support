from __future__ import annotations

import os
from collections.abc import Callable, Iterable, Sequence
from pathlib import Path

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
        for spelling in _SPELLINGS:
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
    """The spelling with its case folded.

    A root configured with a capital in it is the same place on the disks these
    libraries live on -- though not to ``relative_to``, which compares the text.
    A whole report came back empty over exactly that.
    """
    return Path(str(_as_spelled(path)).lower())


def _as_the_disk_has_it(path: Path) -> Path:
    """The path with every junction and link followed: a trip to the disk, which
    on a drive busy syncing can block for minutes, so it is what the two cheap
    spellings fall through to rather than where they start."""
    try:
        return Path(path).resolve()
    except OSError:
        return Path(path)


_SPELLINGS: tuple[Callable[[Path], Path], ...] = (
    _as_spelled,
    _as_folded,
    _as_the_disk_has_it,
)

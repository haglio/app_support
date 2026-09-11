"""One tree of files, another tree of records laid out to match it.

A media library keeps the record of each file out of the tree the files are in:
a clip at some relative path beneath a library root has its record at the same
relative path beneath a second root, with the suffix swapped.  Three apps knew
that rule and each had written it out for itself, from a different starting
point -- one from the two roots it is configured with, two by working the
library root back out of the record root's parent, which assumes a folder name
the configured one never does.  The same rule files the driving scripts under a
third root, which was a fourth copy of it.

What varies between callers is which roots and which suffix, so those are
arguments; the rule is not.  Standard library only.
"""
from __future__ import annotations

import os
from collections.abc import Callable, Sequence
from pathlib import Path

#: What the tree of files is called where it sits beside its mirror.
LIBRARY_DIR_NAME = "videos"


def library_roots_beside(mirror_root: Path) -> tuple[Path, Path]:
    """The roots to measure from, for a caller configured with *mirror_root* alone.

    Two apps are handed the record tree and nothing else, and each had worked
    the library out of it the same way.  The layout both assumed, stated once:
    the library sits beside the mirror under one parent, and that parent comes
    second, so a folder delivered *beside* the library is still measured from
    somewhere.
    """
    mirror_root = Path(mirror_root)
    return (mirror_root.parent / LIBRARY_DIR_NAME, mirror_root.parent)


def mirrored_path(
    source: Path,
    *,
    roots: Sequence[Path],
    mirror_root: Path,
    suffix: str,
) -> Path | None:
    """Where *source*'s counterpart sits under *mirror_root*, or None.

    *roots* are tried in order and the narrower belongs first: a file inside it
    is inside a wider one too, and measured from the wider one its counterpart
    would land a folder deeper, under the narrow root's own name.

    None means *source* is under none of them, which is an ordinary answer --
    a video parked outside the library has no record and wants none.
    """
    for root in roots:
        for spelling in _SPELLINGS:
            try:
                relative = spelling(source).relative_to(spelling(root))
            except ValueError:
                continue
            return (Path(mirror_root) / relative).with_suffix(suffix)
    return None


def _as_spelled(path: Path) -> Path:
    """The path made absolute without asking the disk anything."""
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

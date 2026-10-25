"""Whether a library video is a favorite, said on the record mirroring it, and the page it came from."""
from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

from app_support.json_store import locked_update, read_json
from app_support.mirrored_tree import mirrored_source

FAVORITE_KEY = "favorite"
PAGE_KEY = "web_url"


def is_favorite(record: dict) -> bool:
    return record.get(FAVORITE_KEY) is True


def page_of(record: dict) -> str:
    page = record.get(PAGE_KEY)
    return page if isinstance(page, str) else ""


def mark(record_path: Path, favorite: bool, *, page: str = "") -> bool:
    record_path = Path(record_path)
    if not favorite and not record_path.exists():
        return False

    def marked(record: dict) -> dict | None:
        wanted = {key: value for key, value in record.items()
                  if favorite or key not in (FAVORITE_KEY, PAGE_KEY)}
        if favorite:
            wanted[FAVORITE_KEY] = True
            if page:
                wanted[PAGE_KEY] = page
        return wanted if wanted != record else None

    try:
        return locked_update(record_path, marked) is not None
    except ValueError:
        return False


@dataclass(frozen=True)
class Favorite:
    video: Path
    page: str


def favorites_under(
    record_root: Path, *, video_roots: Sequence[Path], video_suffixes: Iterable[str]
) -> list[Favorite]:
    found = []
    for record_path in sorted(Path(record_root).rglob("*.json")):
        try:
            record = read_json(record_path)
        except (OSError, ValueError):
            continue
        if is_favorite(record):
            video = mirrored_source(record_path, roots=video_roots, mirror_root=record_root,
                                    suffixes=video_suffixes)
            if video is not None:
                found.append(Favorite(video=video, page=page_of(record)))
    return found

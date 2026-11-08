from __future__ import annotations

import uuid
from collections.abc import Iterable, Sequence
from pathlib import Path

from app_support import haglio_settings, mirrored_tree
from app_support.json_store import locked_update, read_json_or_empty

ID_KEY = "id"
REFERENCE_ID_KEY = "video_id"
REFERENCE_PATH_KEY = "video_path"
VIDEO_SUFFIXES = (".mp4", ".mkv", ".mov", ".avi", ".wmv", ".webm", ".m4v")


def _library_records() -> Path:
    return Path(haglio_settings.value("library_root")) / "videos" / "metadata"


def _library_trees() -> tuple[tuple[Path, Sequence[Path]], ...]:
    records = _library_records()
    return ((records, mirrored_tree.library_roots_beside(records)),)


def record_of(video: Path) -> Path | None:
    return mirrored_tree.record_path(video, _library_records())


def recorded_id(record: dict) -> str | None:
    given = record.get(ID_KEY)
    return given if isinstance(given, str) and given else None


def id_of(record_path: Path) -> str:
    record_path = Path(record_path)
    given = recorded_id(read_json_or_empty(record_path))
    if given is not None:
        return given

    def given_one(record: dict) -> dict | None:
        return None if recorded_id(record) else {**record, ID_KEY: uuid.uuid4().hex}

    written = locked_update(record_path, given_one)
    return recorded_id(written if written is not None else read_json_or_empty(record_path)) or ""


def carried_forward(current: dict, replacement: dict) -> dict:
    given = recorded_id(current)
    return replacement if given is None else {**replacement, ID_KEY: given}


def videos_by_id(
    trees: Iterable[tuple[Path, Sequence[Path]]] | None = None, *,
    video_suffixes: Iterable[str] = VIDEO_SUFFIXES,
) -> dict[str, Path]:
    trees = _library_trees() if trees is None else trees
    video_suffixes = tuple(video_suffixes)
    found: dict[str, Path] = {}
    for record_root, video_roots in trees:
        for record_path in sorted(Path(record_root).rglob("*.json")):
            given = recorded_id(read_json_or_empty(record_path))
            if given is None or given in found:
                continue
            video = mirrored_tree.mirrored_source(record_path, roots=video_roots, mirror_root=record_root,
                                    suffixes=video_suffixes)
            if video is not None:
                found[given] = video
    return found


def reference_to(video: Path | str) -> dict[str, str]:
    record = record_of(Path(video)) if Path(video).is_file() else None
    if record is None:
        return {REFERENCE_PATH_KEY: str(video)}
    return {REFERENCE_ID_KEY: id_of(record)}


def video_named_by(reference: dict) -> str | None:
    given = reference.get(REFERENCE_ID_KEY)
    if isinstance(given, str) and given:
        found = videos_by_id().get(given)
        return str(found) if found is not None else None
    path = reference.get(REFERENCE_PATH_KEY)
    return path if isinstance(path, str) and path else None


def named_by_id(holder: dict) -> dict | None:
    path = holder.get(REFERENCE_PATH_KEY)
    if not isinstance(path, str) or not path:
        return None
    reference = reference_to(path)
    if REFERENCE_ID_KEY not in reference:
        return None
    return {**{key: value for key, value in holder.items() if key != REFERENCE_PATH_KEY},
            **reference}

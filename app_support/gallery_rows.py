from __future__ import annotations

import json
import logging
import os
import sqlite3
from collections.abc import Iterable
from pathlib import Path, PurePath

from app_support.comfy_file_refs import frame_name
from app_support.video_ids import VIDEO_SUFFIXES
from app_support.video_names import generation_stem

log = logging.getLogger(__name__)

GENERATED = "generated"
OUTSIDE, STARTING_FRAME, LEFT_OUT = "outside", "starting_frame", "left_out"
MADE_ELSEWHERE = frozenset({OUTSIDE, STARTING_FRAME, LEFT_OUT})


def source_of(row: dict) -> str:
    return row.get("source") or GENERATED


def made_here(row: dict) -> bool:
    return source_of(row) not in MADE_ELSEWHERE


def database(db_path) -> Path:
    db_path = Path(db_path)
    if not db_path.exists():
        raise FileNotFoundError(f"Origenerator database not found: {db_path}")
    return db_path


def rows(columns: Iterable[str], *, db_path, optional: Iterable[str] = ()) -> list[dict]:
    conn = connect_read_only(database(db_path))
    try:
        present = {column[1] for column in conn.execute("PRAGMA table_info(generations)")}
        selected = [*columns, *(name for name in optional if name in present)]
        cursor = conn.execute(f"SELECT {', '.join(selected)} FROM generations")
        return [dict(zip(selected, row, strict=True)) for row in cursor.fetchall()]
    finally:
        conn.close()


def output_names(row: dict) -> list[str]:
    entries = output_entries(row)
    if entries is None:
        log.warning("Could not read what a generation produced: %r", row.get("output_files"))
        return []
    return [entry["filename"] for entry in entries]


def output_entries(row: dict) -> list[dict] | None:
    try:
        return [entry for entry in json.loads(row.get("output_files") or "[]")
                if entry.get("filename")]
    except (AttributeError, TypeError, ValueError):
        return None


def file_entries(row: dict) -> list[dict]:
    try:
        files = json.loads(row.get("output_files") or "[]")
    except (TypeError, ValueError):
        return []
    return [entry for entry in files if isinstance(entry, dict)] if isinstance(files, list) else []


def place_of_its_own(file: dict) -> str | None:
    return file.get("path") or file.get("library_path")


class VideoRows:
    def __init__(self, rows: list[dict]) -> None:
        self._at = {_place(kept): row["prompt_id"] for row in reversed(rows)
                    for file in file_entries(row) if (kept := place_of_its_own(file))}
        self._upscaled_at = {_place(row["evolver_upscale"]): row["prompt_id"]
                             for row in reversed(rows) if row.get("evolver_upscale")}
        self._made_as = {made_as(file["filename"]): row["prompt_id"] for row in reversed(rows)
                         for file in file_entries(row) if file.get("filename")}

    def __call__(self, video) -> str | None:
        place = _place(video)
        return (self._at.get(place) or self._upscaled_at.get(place)
                or self._made_as.get(made_as(video)))


def made_as(name) -> str:
    return generation_stem(PurePath(frame_name(str(name))).stem)


def _place(path) -> str:
    return os.path.normcase(os.path.abspath(path))


def is_video_name(name: str) -> bool:
    return Path(name).suffix.lower() in VIDEO_SUFFIXES


def connect_read_only(db_path: Path) -> sqlite3.Connection:
    uri = Path(db_path).resolve().as_uri() + "?mode=ro"
    return sqlite3.connect(uri, uri=True, timeout=5.0)

from __future__ import annotations

import json
import logging
import sqlite3
from collections.abc import Iterable
from pathlib import Path

from app_support.video_ids import VIDEO_SUFFIXES

log = logging.getLogger(__name__)


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


def is_video_name(name: str) -> bool:
    return Path(name).suffix.lower() in VIDEO_SUFFIXES


def connect_read_only(db_path: Path) -> sqlite3.Connection:
    uri = Path(db_path).resolve().as_uri() + "?mode=ro"
    return sqlite3.connect(uri, uri=True, timeout=5.0)

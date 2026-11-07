from __future__ import annotations

from pathlib import Path

from app_support.sanitize import blocklist_path


def arm_where_the_guard_looks(repo: Path, terms: str) -> Path:
    path = blocklist_path(repo)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(terms, encoding="utf-8")
    return path

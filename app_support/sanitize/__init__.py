"""The pre-publication content guard, and the harvester that feeds it.

Published from here so eleven checkouts share one copy instead of eleven. The
guard refuses a blocklisted term while it is still staged; the harvester learns
new terms off the machine rather than waiting for someone to remember them.

Nothing here knows what any of those terms *are*. Every list this package reads
— the blocklist, the directory roots to walk, the vocabulary that decides which
harvested terms are worth keeping — lives in git-ignored ``sanitize/*.local.txt``
files beside each checkout, because the lists describe the machine and a
committed copy of one would be the catalogue it exists to keep out of the repo.

    python -m app_support.sanitize --staged          # pre-commit
    python -m app_support.sanitize --message FILE    # commit-msg
"""
from __future__ import annotations

from app_support.sanitize.guard import (
    Violation,
    blocklist_path,
    find_violations,
    load_blocklist,
    main,
    scan_files,
)

__all__ = [
    "Violation",
    "blocklist_path",
    "find_violations",
    "load_blocklist",
    "main",
    "scan_files",
]

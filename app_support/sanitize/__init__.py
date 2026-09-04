"""The pre-publication content guard.

Published from here so eleven checkouts share one copy instead of eleven. The
guard refuses a blocklisted term while it is still staged.

Nothing here knows what any of those terms *are*. The one list lives beside the
family of checkouts rather than inside any of them — it describes the machine,
and a committed copy of it would be the catalogue it exists to keep out.

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

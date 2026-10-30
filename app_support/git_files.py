"""What a repository holds at a revision, read without checking it out.

Standard library only.
"""
from __future__ import annotations

import subprocess
from pathlib import Path


def git(root: Path, *args: str) -> str:
    """Named encoding, not the machine's: a source file is UTF-8 wherever it is
    read, and Windows' own code page cannot decode five of its bytes."""
    done = subprocess.run(["git", "-C", str(root), *args], check=True,
                          capture_output=True, encoding="utf-8")
    return done.stdout

"""What a repository holds at a revision, read without checking it out.

Standard library only.
"""
from __future__ import annotations

import subprocess
from collections.abc import Callable
from pathlib import Path


def git(root: Path, *args: str) -> str:
    """Named encoding, not the machine's: a source file is UTF-8 wherever it is
    read, and Windows' own code page cannot decode five of its bytes."""
    done = subprocess.run(["git", "-C", str(root), *args], check=True,
                          capture_output=True, encoding="utf-8")
    return done.stdout


def files_at(root: Path, revision: str, wanted: Callable[[str], bool]) -> dict[str, str]:
    blobs = []
    for entry in git(root, "ls-tree", "-r", "-z", "--full-tree", revision).split("\0"):
        if entry:
            about, path = entry.split("\t", 1)
            _mode, kind, sha = about.split()
            if kind == "blob" and wanted(path):
                blobs.append((path, sha))
    return dict(zip((path for path, _ in blobs), _contents(root, [sha for _, sha in blobs]), strict=True))


def _contents(root: Path, shas: list[str]) -> list[str]:
    if not shas:
        return []
    batch = subprocess.run(["git", "-C", str(root), "cat-file", "--batch"], check=True, capture_output=True,
                           input="".join(f"{sha}\n" for sha in shas).encode("ascii")).stdout
    contents, at = [], 0
    for _sha in shas:
        header_ends = batch.index(b"\n", at)
        size = int(batch[at:header_ends].split()[2])
        contents.append(batch[header_ends + 1: header_ends + 1 + size].decode("utf-8", errors="replace"))
        at = header_ends + 1 + size + 1
    return contents

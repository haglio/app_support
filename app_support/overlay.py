from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any


def overlay_path(local_path: Path, example_path: Path) -> Path:
    return local_path if local_path.exists() else example_path


def read_overlay(local_path: Path, example_path: Path) -> dict[str, Any]:
    return json.loads(overlay_path(local_path, example_path).read_text(encoding="utf-8"))


def documented_keys(example: Mapping[str, Any]) -> set[str]:
    return {key for key in example if not key.startswith("_")}


def backfilled(
    data: dict[str, Any], example: Mapping[str, Any], *,
    empty_when_absent: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    absent = empty_when_absent or {}
    for key, example_value in example.items():
        if key.startswith("_") or key in data:
            continue
        data[key] = absent.get(key, example_value)
    return data


def missing_keys(local_path: Path, example_path: Path) -> tuple[str, ...]:
    return keys_lacking(local_path, json.loads(example_path.read_text(encoding="utf-8")))


def keys_lacking(local_path: Path, example: Mapping[str, Any]) -> tuple[str, ...]:
    if not local_path.exists():
        return ()
    present = set(json.loads(local_path.read_text(encoding="utf-8")))
    return tuple(sorted(documented_keys(example) - present))


class MissingOverlayKey(LookupError):
    def __init__(self, keys: tuple[str, ...], path: Path | None = None):
        self.keys = tuple(keys)
        self.path = path
        where = f"the content overlay {path}" if path is not None else "the content overlay"
        super().__init__(
            f"{where} has no {' -> '.join(self.keys)}. The git-ignored content.local.json replaces "
            f"content.example.json rather than merging with it, so it has to carry every key that one does, "
            f"and a file kept by hand gains none when the app does."
        )


def overlay_value(content: Mapping[str, Any], *keys: str, path: Path | None = None) -> Any:
    here: Any = content
    for depth, key in enumerate(keys, start=1):
        if not isinstance(here, Mapping) or key not in here:
            raise MissingOverlayKey(keys[:depth], path)
        here = here[key]
    return here

"""Reading a JSON config the way every app's loader does, with refusals that say what.

Four loaders read the same shape of file -- a JSON object of sections and values,
paths relative to the file that holds them -- and three of them answered a
missing key with a bare ``KeyError`` that names neither the key nor the file,
raised from inside a launcher with no console to raise into.  The fourth had
grown these; they are here so all four say the same thing.

Each refusal names the dotted key and the file it was looked for in.  Standard
library only.
"""
from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any


def read_json_config(path: Path, *, default_dir: Path) -> tuple[Path, dict[str, Any]]:
    """*path* resolved against *default_dir* when relative, and its parsed object.

    The resolved path comes back with the data because every loader keeps it:
    the sections' relative paths hang off the file's own directory.
    """
    path = Path(path).expanduser()
    if not path.is_absolute():
        path = (default_dir / path).resolve()
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")
    with path.open("r", encoding="utf-8") as handle:
        return path, json.load(handle)


def resolve_path(base: Path, raw: str | Path) -> Path:
    """*raw* as given when absolute, else under *base* -- the config's own directory."""
    path = Path(raw)
    return path if path.is_absolute() else (base / path).resolve()


def _dotted(context: str, key: str) -> str:
    return f"{context}.{key}" if context else key


def require_section(
    parent: dict[str, Any], key: str, source: Path, *, context: str = "config",
) -> dict[str, Any]:
    """The object at *key*, or a refusal naming it."""
    value = parent.get(key)
    if value is None:
        raise ValueError(f"Missing required config section: {_dotted(context, key)} (in {source})")
    if not isinstance(value, dict):
        raise TypeError(f"Expected object for config section: {_dotted(context, key)} (in {source})")
    return value


def optional_section(
    parent: dict[str, Any], key: str, source: Path, *, context: str = "config",
) -> dict[str, Any] | None:
    """The object at *key*, ``None`` when it is not there -- and still a refusal
    when it is there and is not an object."""
    value = parent.get(key)
    if value is None:
        return None
    if not isinstance(value, dict):
        raise TypeError(f"Expected object for config section: {_dotted(context, key)} (in {source})")
    return value


def require_value(parent: dict[str, Any], key: str, source: Path, *, context: str = "config") -> Any:
    """The value at *key*, or a refusal naming it."""
    value = parent.get(key)
    if value is None:
        raise ValueError(f"Missing required config value: {_dotted(context, key)} (in {source})")
    return value


def require_path(
    parent: dict[str, Any], key: str, source: Path, *, base: Path, context: str = "config",
) -> Path:
    """The path at *key*, resolved against *base* when relative."""
    return resolve_path(base, require_value(parent, key, source, context=context))


def require_typed(
    parent: dict[str, Any], key: str, source: Path, *, cast: Callable[[Any], Any],
    context: str = "config",
) -> Any:
    """The value at *key* through *cast* -- ``int``, ``float``, ``bool``, ``str``."""
    return cast(require_value(parent, key, source, context=context))

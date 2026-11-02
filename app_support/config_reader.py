from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any


def read_json_config(path: Path, *, default_dir: Path) -> tuple[Path, dict[str, Any]]:
    path = Path(path).expanduser()
    if not path.is_absolute():
        path = (default_dir / path).resolve()
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")
    with path.open("r", encoding="utf-8") as handle:
        return path, json.load(handle)


def resolve_path(base: Path, raw: str | Path) -> Path:
    path = Path(raw)
    return path if path.is_absolute() else (base / path).resolve()


def _dotted(context: str, key: str) -> str:
    return f"{context}.{key}" if context else key


def require_section(
    parent: dict[str, Any], key: str, source: Path, *, context: str = "config",
) -> dict[str, Any]:
    value = parent.get(key)
    if value is None:
        raise ValueError(f"Missing required config section: {_dotted(context, key)} (in {source})")
    if not isinstance(value, dict):
        raise TypeError(f"Expected object for config section: {_dotted(context, key)} (in {source})")
    return value


def optional_section(
    parent: dict[str, Any], key: str, source: Path, *, context: str = "config",
) -> dict[str, Any] | None:
    value = parent.get(key)
    if value is None:
        return None
    if not isinstance(value, dict):
        raise TypeError(f"Expected object for config section: {_dotted(context, key)} (in {source})")
    return value


def require_value(parent: dict[str, Any], key: str, source: Path, *, context: str = "config") -> Any:
    value = parent.get(key)
    if value is None:
        raise ValueError(f"Missing required config value: {_dotted(context, key)} (in {source})")
    return value


def require_path(
    parent: dict[str, Any], key: str, source: Path, *, base: Path, context: str = "config",
) -> Path:
    return resolve_path(base, require_value(parent, key, source, context=context))


def require_typed(
    parent: dict[str, Any], key: str, source: Path, *, cast: Callable[[Any], Any],
    context: str = "config",
) -> Any:
    return cast(require_value(parent, key, source, context=context))

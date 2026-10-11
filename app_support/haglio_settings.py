"""The settings all of Haglio shares, written once in ``~/.haglio/settings.json``.

What more than one app needs to know about this machine and its library is kept
here rather than in each app's own overlay, so a change to it is made once and
every app has it.  The file says where the library is, so it lives outside the
library.  A public checkout, and every suite, runs on :data:`EXAMPLE` instead.
Standard library only.
"""
from __future__ import annotations

import copy
import json
import os
from pathlib import Path
from typing import Any

from app_support import siblings

SETTINGS_ENV = "HAGLIO_SETTINGS"
THE_EXAMPLE = "example"

EXAMPLE: dict[str, Any] = {
    "library_root": "C:/path/to/library-root",
    "project_roots": [],
    "genau_flick_words": {"one": "flick", "many": "flicks"},
    "genau_source": "example-loop-clips",
    "ambient_audio_dir": "videos/example-folder/ambient-clips",
}


def settings_file() -> Path:
    named = os.environ.get(SETTINGS_ENV)
    return Path(named) if named else Path.home() / ".haglio" / "settings.json"


def load() -> dict[str, Any]:
    path = settings_file()
    if os.environ.get(SETTINGS_ENV) == THE_EXAMPLE or not path.is_file():
        return copy.deepcopy(EXAMPLE)
    return json.loads(path.read_text(encoding="utf-8"))


class MissingSetting(LookupError):
    def __init__(self, keys: tuple[str, ...], path: Path):
        self.keys = keys
        self.path = path
        super().__init__(f"the Haglio settings in {path} have no {' -> '.join(keys)}")


def value(*keys: str) -> Any:
    here: Any = load()
    for depth, key in enumerate(keys, start=1):
        if not isinstance(here, dict) or key not in here:
            raise MissingSetting(keys[:depth], settings_file())
        here = here[key]
    return here


def project_roots() -> tuple[Path, ...]:
    return siblings.project_roots(load().get("project_roots"), fallback=Path(value("library_root")) / "projects")

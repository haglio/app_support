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
    "genau_dir": "C:/path/to/library-root/videos/videos/genau",
    "kino_dir": "C:/path/to/library-root/videos/videos/kino",
    "genau_audio_dir": "C:/path/to/library-root/videos/audio/genau",
    "origenerator_images_dir": "C:/path/to/library-root/images/origenerator",
    "origenerator_videos_dir": "C:/path/to/library-root/videos/videos/origenerator",
    "origenerator_scripts_dir": "C:/path/to/library-root/videos/scripts/origenerator",
    "origenerator_audio_dir": "C:/path/to/library-root/videos/audio/origenerator",
    "warm_gun_journal_dir": "C:/path/to/library-root/app_data/warm_gun",
    "funscript_corpus_dir": "C:/path/to/library-root/app_data/funestra/funscript_corpus",
    "microphone": "Example microphone",
    "vosk_model": "vosk-model-en-us-0.22-lgraph",
}


def settings_file() -> Path:
    named = os.environ.get(SETTINGS_ENV)
    outside_the_library_whose_place_it_names = Path.home() / ".haglio" / "settings.json"
    return Path(named) if named else outside_the_library_whose_place_it_names


_read_at: dict[Path, tuple[tuple[int, int], dict[str, Any]]] = {}


def _as_read(path: Path) -> dict[str, Any]:
    if os.environ.get(SETTINGS_ENV) == THE_EXAMPLE:
        return EXAMPLE
    try:
        stamp = path.stat()
    except OSError:
        return EXAMPLE
    dated = (stamp.st_mtime_ns, stamp.st_size)
    kept = _read_at.get(path)
    if kept is None or kept[0] != dated:
        kept = _read_at[path] = (dated, json.loads(path.read_text(encoding="utf-8")))
    return kept[1]


def load() -> dict[str, Any]:
    return copy.deepcopy(_as_read(settings_file()))


class MissingSetting(LookupError):
    def __init__(self, keys: tuple[str, ...], path: Path):
        self.keys = keys
        self.path = path
        super().__init__(f"the Haglio settings in {path} have no {' -> '.join(keys)}")


def value(*keys: str) -> Any:
    here: Any = _as_read(settings_file())
    for depth, key in enumerate(keys, start=1):
        if not isinstance(here, dict) or key not in here:
            raise MissingSetting(keys[:depth], settings_file())
        here = here[key]
    return copy.deepcopy(here)


def project_roots() -> tuple[Path, ...]:
    return siblings.project_roots(_as_read(settings_file()).get("project_roots"), fallback=Path(value("library_root")) / "projects")


def example_inside(folder: Path) -> dict[str, Any]:
    library = folder / "library"
    example_root = EXAMPLE["library_root"]
    return {name: str(library) + setting[len(example_root):]
            if isinstance(setting, str) and setting.startswith(example_root) else copy.deepcopy(setting)
            for name, setting in EXAMPLE.items()}


def reaching_outside(settings: dict[str, Any], folder: Path) -> list[str]:
    return [name for name, setting in settings.items()
            if any(_outside(path, folder) for path in (setting if isinstance(setting, list) else [setting]))]


def _outside(setting: Any, folder: Path) -> bool:
    return isinstance(setting, str) and Path(setting).is_absolute() and not Path(setting).is_relative_to(folder)


def run_on(settings: dict[str, Any], folder: Path, environ) -> None:
    written = folder / "haglio_settings.json"
    folder.mkdir(parents=True, exist_ok=True)
    written.write_text(json.dumps(settings), encoding="utf-8")
    environ[SETTINGS_ENV] = str(written)

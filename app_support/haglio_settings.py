from __future__ import annotations

import copy
import json
import os
from pathlib import Path
from typing import Any

from app_support import siblings
from app_support.written_file import ReadWhenChanged

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


def the_computers_own_file() -> Path:
    return Path.home() / ".haglio" / "settings.json"


def settings_file() -> Path:
    named = os.environ.get(SETTINGS_ENV)
    return Path(named) if named else the_computers_own_file()


_readers: dict[Path, ReadWhenChanged[dict[str, Any]]] = {}


def _as_read(path: Path) -> dict[str, Any]:
    if os.environ.get(SETTINGS_ENV) == THE_EXAMPLE:
        return EXAMPLE
    reader = _readers.get(path) or _readers.setdefault(path, ReadWhenChanged(path, _read_or_the_example))
    read = reader.latest()
    return EXAMPLE if read is None else read


def _read_if_there(path: Path) -> dict[str, Any] | None:
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    return json.loads(text)


def _read_or_the_example(path: Path) -> dict[str, Any]:
    read = _read_if_there(path)
    return EXAMPLE if read is None else read


def load() -> dict[str, Any]:
    return copy.deepcopy(_as_read(settings_file()))


class MissingSetting(LookupError):
    def __init__(self, keys: tuple[str, ...], path: Path):
        self.keys = keys
        self.path = path
        super().__init__(f"the Haglio settings in {path} have no {' -> '.join(keys)}")


def _looked_up(settings: Any, keys: tuple[str, ...], path: Path) -> Any:
    here = settings
    for depth, key in enumerate(keys, start=1):
        if not isinstance(here, dict) or key not in here:
            raise MissingSetting(keys[:depth], path)
        here = here[key]
    return copy.deepcopy(here)


def value(*keys: str) -> Any:
    return _looked_up(_as_read(settings_file()), keys, settings_file())


def the_computers_library() -> Path | None:
    own = the_computers_own_file()
    settings = _read_if_there(own)
    return None if settings is None else Path(_looked_up(settings, ("library_root",), own))


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

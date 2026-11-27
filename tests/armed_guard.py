from __future__ import annotations

import json
from pathlib import Path

import pytest

from app_support.sanitize import blocklist_path


class Computer:
    def __init__(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        self.home = tmp_path / "home"
        self.library = tmp_path / "library"
        self.home.mkdir()
        for where_each_platform_finds_the_home_folder in ("HOME", "USERPROFILE"):
            monkeypatch.setenv(where_each_platform_finds_the_home_folder, str(self.home))

    def name_its_library(self, settings: dict | None = None) -> Path:
        haglio = self.home / ".haglio"
        haglio.mkdir(exist_ok=True)
        written = {"library_root": str(self.library)} if settings is None else settings
        (haglio / "settings.json").write_text(json.dumps(written), encoding="utf-8")
        return self.library

    def arm(self, terms: str) -> Path:
        self.name_its_library()
        path = blocklist_path()
        assert path is not None
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(terms, encoding="utf-8")
        return path

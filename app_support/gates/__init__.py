"""The family's gates, which a repository asks for by naming ``app_support.gates.pytest_plugin`` once."""
from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path

from app_support.dead_code import packages_under
from app_support.dependencies import is_a_family_sibling

_WHITELISTS = ("vulture_whitelist.py", "vulture_whitelist.txt")


@dataclass(frozen=True)
class Checkout:
    root: Path

    @classmethod
    def of(cls, config) -> Checkout:
        assert config.inipath, "no pyproject declares this repo's pytest options"
        return cls(Path(config.inipath).parent)

    @property
    def pyproject(self) -> Path:
        return self.root / "pyproject.toml"

    @property
    def is_a_library(self) -> bool:
        return is_a_family_sibling(self.pyproject)

    def numbers(self, gate: str) -> dict:
        document = tomllib.loads(self.pyproject.read_text(encoding="utf-8"))
        return document.get("tool", {}).get("haglio", {}).get(gate, {})

    @property
    def packages(self) -> tuple[Path, ...]:
        return tuple(sorted(self.root / name for name in packages_under(self.root) - {"tests", "tools"}))

    @property
    def root_modules(self) -> tuple[Path, ...]:
        return tuple(sorted(path for path in self.root.glob("*.py") if path.name not in _WHITELISTS))

    @property
    def tools(self) -> tuple[Path, ...]:
        tools = self.root / "tools"
        return (tools,) if any(tools.rglob("*.py")) else ()

    @property
    def tests(self) -> Path:
        return self.root / "tests"

    @property
    def ships(self) -> tuple[Path, ...]:
        return (*self.packages, *self.root_modules)

    @property
    def code(self) -> tuple[Path, ...]:
        return (*self.ships, *self.tools)

    @property
    def own_names(self) -> tuple[str, ...]:
        return tuple(path.stem for path in self.ships)

    @property
    def whitelist(self) -> Path | None:
        return next((self.root / name for name in _WHITELISTS if (self.root / name).is_file()), None)

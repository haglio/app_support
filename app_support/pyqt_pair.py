from __future__ import annotations

import re
import tomllib
from pathlib import Path

_NAME = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)")
_FLOOR_AND_CEILING = re.compile(r">=(\d+)\.(\d+)(?:\.\d+)?\s*,\s*<(\d+)\.(\d+)")


def _the_one_minor_admitted(requirement: str) -> str | None:
    found = _FLOOR_AND_CEILING.search(requirement)
    if not found:
        return None
    major, minor, ceiling_major, ceiling_minor = map(int, found.groups())
    return f"{major}.{minor}" if (ceiling_major, ceiling_minor) == (major, minor + 1) else None


def assert_pyqt6_and_its_webengine_are_held_to_one_minor(pyproject: Path) -> None:
    __tracebackhide__ = True
    requirements = tomllib.loads(pyproject.read_text(encoding="utf-8")).get("project", {}).get("dependencies", [])
    held = {_NAME.match(requirement)[1].lower().replace("_", "-"): requirement for requirement in requirements}
    if "pyqt6-webengine" not in held:
        return
    minors = {_the_one_minor_admitted(held.get(name, "")) for name in ("pyqt6", "pyqt6-webengine")}
    assert len(minors - {None}) == len(minors) == 1, (
        f"PyQt6 and PyQt6-WebEngine must each admit one minor, the same one: "
        f"{held.get('pyqt6')!r} and {held['pyqt6-webengine']!r}")

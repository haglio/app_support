"""Where this package's version comes from.

Consumers pin a version of this package rather than running whatever checkout
sits beside them, so the version has to be a thing that moves. A number written
into `pyproject.toml` does not: this one said 0.1.0 from the day the repo was
made until the day pinning arrived, through every landing in between. The tag on
each landing is what moves, so the tag is what the version is read from.
"""
from __future__ import annotations

import tomllib
from pathlib import Path

PYPROJECT = Path(__file__).resolve().parent.parent / "pyproject.toml"


def _pyproject() -> dict:
    return tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))


def test_the_version_is_not_written_down():
    project = _pyproject()["project"]

    assert "version" not in project, (
        "a version written here is a version nobody bumps; declare it dynamic "
        "and let the tag say what it is"
    )


def test_the_version_is_declared_dynamic():
    assert "version" in _pyproject()["project"].get("dynamic", [])


def test_the_build_reads_the_version_from_git():
    raw = _pyproject()

    assert "setuptools_scm" in raw.get("tool", {}), (
        "[tool.setuptools_scm] is what tells the build to read the tag"
    )
    assert any(req.startswith("setuptools-scm") for req in raw["build-system"]["requires"]), (
        "the build cannot read the tag without setuptools-scm among its requires"
    )

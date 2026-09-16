"""This package's version is the tag on its landing, so a consumer can pin it."""
from __future__ import annotations

from pathlib import Path

from app_support.dependencies import assert_the_version_comes_from_the_tag

ROOT = Path(__file__).resolve().parent.parent


def test_the_version_comes_from_the_tag():
    assert_the_version_comes_from_the_tag(ROOT / "pyproject.toml")

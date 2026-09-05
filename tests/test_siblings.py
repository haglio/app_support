"""Where the other checkouts are: the walk that finds a sibling from a clone and
from a worktree alike, the sys.path rule, and the overlay's project roots.
Every checkout here is a fabricated tree under tmp_path."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

from app_support.siblings import (
    ensure_sibling_importable,
    project_dir,
    project_roots,
    sibling_checkout,
)


def _family(tmp_path: Path) -> Path:
    """Two checkouts side by side, each with its package one level down."""
    family = tmp_path / "family"
    for name in ("someapp", "widgetlib"):
        package = family / name / name
        package.mkdir(parents=True)
        (package / "__init__.py").write_text("", encoding="utf-8")
    (family / "widgetlib" / "tests").mkdir()
    return family


class TestSiblingCheckout:
    def test_found_beside_this_checkout(self, tmp_path: Path):
        family = _family(tmp_path)

        found = sibling_checkout("widgetlib", near=family / "someapp" / "someapp" / "paths.py")

        assert found == family / "widgetlib"

    def test_a_worktree_finds_the_same_primary(self, tmp_path: Path):
        # The walk goes up past .claude/worktrees/<x> to where the siblings sit.
        family = _family(tmp_path)
        worktree = family / "someapp" / ".claude" / "worktrees" / "feature" / "someapp"
        worktree.mkdir(parents=True)

        assert sibling_checkout("widgetlib", near=worktree / "paths.py") == family / "widgetlib"

    def test_a_directory_that_merely_shares_the_name_is_not_it(self, tmp_path: Path):
        # The repo directory is the package's name too; only the one with the
        # package inside is the checkout.
        family = _family(tmp_path)
        (family / "someapp" / "widgetlib").mkdir()  # no widgetlib/widgetlib/__init__.py

        assert sibling_checkout("widgetlib", near=family / "someapp" / "someapp" / "x.py") == (
            family / "widgetlib")

    def test_nothing_found_is_said_rather_than_guessed(self, tmp_path: Path):
        with pytest.raises(RuntimeError, match="widgetlib"):
            sibling_checkout("widgetlib", near=tmp_path / "alone" / "x.py")


class TestEnsureSiblingImportable:
    def test_the_checkout_goes_on_the_path_at_the_back(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        # At the back: the checkout also holds the sibling's own tests and
        # tools packages, which at the front shadow the app's.
        family = _family(tmp_path)
        monkeypatch.setattr(sys, "path", ["C:/somewhere/first"])

        ensure_sibling_importable("widgetlib", near=family / "someapp" / "someapp" / "x.py")

        assert sys.path == ["C:/somewhere/first", str(family / "widgetlib")]

    def test_a_name_something_already_provides_is_left_to_it(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        # A session that chose a checkout through PYTHONPATH keeps it; json is
        # a stand-in for a name that resolves to a real module.
        monkeypatch.setattr(sys, "path", list(sys.path))
        before = list(sys.path)

        ensure_sibling_importable("json", near=tmp_path / "x.py")

        assert sys.path == before

    def test_it_is_put_on_the_path_once(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        family = _family(tmp_path)
        monkeypatch.setattr(sys, "path", [str(family / "widgetlib")])

        ensure_sibling_importable("widgetlib", near=family / "someapp" / "someapp" / "x.py")

        assert sys.path.count(str(family / "widgetlib")) == 1


class TestProjectRoots:
    def test_an_overlay_that_says_nothing_means_the_fallback(self, tmp_path: Path):
        assert project_roots({}, fallback=tmp_path / "projects") == (tmp_path / "projects",)
        assert project_roots({"project_roots": []}, fallback=tmp_path) == (tmp_path,)

    def test_the_overlays_roots_in_its_order(self, tmp_path: Path):
        roots = project_roots({"project_roots": ["D:/repos", "C:/old"]}, fallback=tmp_path)

        assert roots == (Path("D:/repos"), Path("C:/old"))


class TestProjectDir:
    def test_the_first_root_that_holds_the_checkout(self, tmp_path: Path):
        (tmp_path / "new").mkdir()
        (tmp_path / "old" / "someapp").mkdir(parents=True)

        assert project_dir("someapp", (tmp_path / "new", tmp_path / "old")) == tmp_path / "old" / "someapp"

    def test_a_sibling_nobody_has_is_a_path_under_the_first_root_not_a_crash(self, tmp_path: Path):
        assert project_dir("someapp", (tmp_path / "new", tmp_path / "old")) == tmp_path / "new" / "someapp"

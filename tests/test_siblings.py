"""Where the other checkouts are: the walk that finds a sibling from a clone and
from a worktree alike, the sys.path rule, the overlay's project roots, and the
refusal of a suite that imported its package from a different checkout.
Every checkout here is a fabricated tree under tmp_path."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

from app_support.siblings import (
    assert_imported_from_checkout,
    checkouts_that_import,
    ensure_sibling_importable,
    primary_checkout_of,
    project_dir,
    project_roots,
    sibling_checkout,
    workspace_of,
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

    def test_a_renamed_sibling_is_found_under_the_name_its_checkout_had_before(
            self, tmp_path: Path):
        family = _family(tmp_path)
        (family / "player_core" / "player_core").mkdir(parents=True)
        (family / "player_core" / "player_core" / "__init__.py").write_text("", encoding="utf-8")

        assert sibling_checkout("funestra", near=family / "someapp" / "someapp" / "x.py") == (
            family / "player_core")

    def test_a_renamed_siblings_checkout_under_its_new_name_comes_first(self, tmp_path: Path):
        family = _family(tmp_path)
        for name in ("funestra", "player_core"):
            (family / name / name).mkdir(parents=True)
            (family / name / name / "__init__.py").write_text("", encoding="utf-8")

        assert sibling_checkout("funestra", near=family / "someapp" / "someapp" / "x.py") == (
            family / "funestra")

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
        assert project_roots(None, fallback=tmp_path / "projects") == (tmp_path / "projects",)
        assert project_roots([], fallback=tmp_path) == (tmp_path,)

    def test_the_overlays_roots_in_its_order(self, tmp_path: Path):
        roots = project_roots(["D:/repos", "C:/old"], fallback=tmp_path)

        assert roots == (Path("D:/repos"), Path("C:/old"))


class TestProjectDir:
    def test_the_first_root_that_holds_the_checkout(self, tmp_path: Path):
        (tmp_path / "new").mkdir()
        (tmp_path / "old" / "someapp").mkdir(parents=True)

        assert project_dir("someapp", (tmp_path / "new", tmp_path / "old")) == tmp_path / "old" / "someapp"

    def test_a_sibling_nobody_has_is_a_path_under_the_first_root_not_a_crash(self, tmp_path: Path):
        assert project_dir("someapp", (tmp_path / "new", tmp_path / "old")) == tmp_path / "new" / "someapp"

    def test_a_renamed_siblings_folder_is_found_under_its_old_name_too(self, tmp_path: Path):
        (tmp_path / "root" / "player_core").mkdir(parents=True)

        assert project_dir("funestra", (tmp_path / "root",)) == tmp_path / "root" / "player_core"

    def test_a_renamed_siblings_folder_under_its_new_name_comes_first(self, tmp_path: Path):
        for name in ("funestra", "player_core"):
            (tmp_path / "root" / name).mkdir(parents=True)

        assert project_dir("funestra", (tmp_path / "root",)) == tmp_path / "root" / "funestra"


def _imported(name: str, file: Path | None) -> ModuleType:
    """A module object standing in for one already imported; ``None`` is what a
    namespace package reports for its file."""
    module = ModuleType(name)
    module.__file__ = None if file is None else str(file)
    return module


class TestTheCheckoutUnderTest:
    def test_refuses_a_package_imported_from_another_checkout(self, tmp_path: Path):
        # A worktree's suite that resolves the package from the primary is green
        # about code the branch never changed.
        family = _family(tmp_path)
        primary = family / "widgetlib" / "widgetlib" / "__init__.py"
        worktree = family / "widgetlib" / ".claude" / "worktrees" / "feature"

        with pytest.raises(RuntimeError, match="PYTHONPATH"):
            assert_imported_from_checkout(_imported("widgetlib", primary), checkout=worktree)

    def test_accepts_the_package_that_lives_in_this_checkout(self, tmp_path: Path):
        family = _family(tmp_path)
        checkout = family / "widgetlib"

        assert_imported_from_checkout(
            _imported("widgetlib", checkout / "widgetlib" / "__init__.py"), checkout=checkout)

    def test_refuses_a_namespace_package_which_is_no_checkout_at_all(self, tmp_path: Path):
        # The checkout directory shares the package's name, so with the family's
        # parent on the path the name resolves to an empty namespace portion and
        # every submodule under it comes from somewhere else.
        family = _family(tmp_path)

        with pytest.raises(RuntimeError, match="PYTHONPATH"):
            assert_imported_from_checkout(_imported("widgetlib", None),
                                          checkout=family / "widgetlib")


class TestWhereTheCheckoutsAre:
    def _module_in(self, checkout: Path) -> Path:
        (checkout / "app_support").mkdir(parents=True)
        (checkout / "pyproject.toml").write_text("", encoding="utf-8")
        module = checkout / "app_support" / "siblings.py"
        module.write_text("", encoding="utf-8")
        return module

    def test_they_are_beside_the_checkout_this_runs_from(self, tmp_path: Path):
        module = self._module_in(tmp_path / "workspace" / "app_support")

        assert workspace_of(module) == tmp_path / "workspace"

    def test_from_a_worktree_they_are_beside_its_primary_checkout(self, tmp_path: Path):
        primary = tmp_path / "workspace" / "app_support"
        self._module_in(primary)
        _commit_everything_in(primary)
        worktree = _worktree_of(primary, primary / ".claude" / "worktrees" / "some-branch")

        assert workspace_of(worktree / "app_support" / "siblings.py") == tmp_path / "workspace"

    def test_a_copy_installed_into_a_venv_has_to_be_told(self, tmp_path: Path):
        module = tmp_path / "venv" / "Lib" / "site-packages" / "app_support" / "siblings.py"
        module.parent.mkdir(parents=True)
        module.write_text("", encoding="utf-8")

        with pytest.raises(ValueError, match="--workspace"):
            workspace_of(module)


def _commit_everything_in(checkout: Path) -> None:
    for args in (("init", "-q", "-b", "main"), ("config", "user.email", "someone@example.com"),
                 ("config", "user.name", "Someone"), ("add", "-A"), ("commit", "-q", "-m", "the base")):
        subprocess.run(["git", "-C", str(checkout), *args], check=True, capture_output=True)


def _worktree_of(primary: Path, place: Path) -> Path:
    subprocess.run(["git", "-C", str(primary), "worktree", "add", "-q", str(place)], check=True,
                   capture_output=True)
    return place


class TestThePrimaryCheckout:
    @pytest.fixture
    def primary(self, tmp_path: Path) -> Path:
        checkout = tmp_path / "someapp"
        (checkout / "pkg").mkdir(parents=True)
        (checkout / "pkg" / "module.py").write_text("", encoding="utf-8")
        _commit_everything_in(checkout)
        return checkout

    def test_a_worktree_belongs_to_the_checkout_it_was_made_in(self, primary: Path):
        worktree = _worktree_of(primary, primary / ".claude" / "worktrees" / "some-branch")

        assert primary_checkout_of(worktree) == primary

    def test_a_worktree_made_anywhere_else_belongs_to_the_checkout_it_was_made_in(
            self, primary: Path, tmp_path: Path):
        worktree = _worktree_of(primary, tmp_path / "scratch" / "some-branch")

        assert primary_checkout_of(worktree) == primary

    def test_a_checkout_is_its_own(self, primary: Path):
        assert primary_checkout_of(primary) == primary

    def test_a_folder_inside_a_checkout_belongs_to_that_checkout(self, primary: Path):
        assert primary_checkout_of(primary / "pkg") == primary

    @pytest.mark.parametrize("folder", ["someapp", "someapp/.claude/worktrees/some-branch"])
    def test_a_folder_git_does_not_know_is_its_own(self, tmp_path: Path, folder: str):
        (tmp_path / folder).mkdir(parents=True)

        assert primary_checkout_of(tmp_path / folder) == tmp_path / folder


class TestTheCheckoutsThatImportAPackage:
    def test_they_are_the_checkouts_beside_it_whose_code_imports_it(self, checkout_tracking):
        library = checkout_tracking("widgetlib", {"pyproject.toml": "", "widgetlib/__init__.py": ""})
        someapp = checkout_tracking("someapp", {"parlour.py": "from widgetlib import hinges\n"})
        otherapp = checkout_tracking(
            "otherapp", {"drawing_room.py": "def f():\n    import widgetlib.hinges\n"})
        checkout_tracking("unrelated", {"study.py": "import widgetlibrary\n"})

        found = checkouts_that_import("widgetlib", near=library / "tests" / "test_dead_code.py")

        assert found == [otherapp, someapp]

    def test_a_checkout_holding_the_package_is_a_copy_of_it_and_no_caller(self, checkout_tracking):
        """A worktree's own primary, and the old-named clone this machine keeps of
        funestra: read as callers, they count the package's names as used."""
        package = {"pyproject.toml": "", "widgetlib/__init__.py": "",
                   "tests/test_hinges.py": "from widgetlib import hinges\n"}
        primary = checkout_tracking("widgetlib", package)
        checkout_tracking("widgetlib_before_the_rename", package)
        subprocess.run(["git", "-C", str(primary), "-c", "user.email=someone@example.com", "-c",
                        "user.name=Someone", "commit", "-q", "-m", "the base"], check=True, capture_output=True)
        worktree = _worktree_of(primary, primary / ".claude" / "worktrees" / "some-branch")

        assert checkouts_that_import("widgetlib", near=worktree / "tests" / "test_dead_code.py") == []

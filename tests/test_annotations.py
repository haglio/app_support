"""The deferred-annotations gate: which modules defer, and what the assertion says.
Every module and package here is invented."""
from __future__ import annotations

from pathlib import Path

import pytest

from app_support.annotations import (
    assert_every_module_defers_annotations,
    modules_evaluating_their_annotations,
)

DEFERRED = "from __future__ import annotations\n"


def _package(tmp_path: Path, **modules: str) -> Path:
    package = tmp_path / "someapp"
    package.mkdir()
    for name, source in modules.items():
        (package / f"{name}.py").write_text(source, encoding="utf-8")
    return tmp_path


class TestModulesEvaluatingTheirAnnotations:
    def test_a_module_with_the_future_import_is_not_reported(self, tmp_path: Path):
        root = _package(tmp_path, app=DEFERRED + "def build(item: Later) -> None: ...\n")

        assert modules_evaluating_their_annotations(root, [root / "someapp"]) == []

    def test_a_module_without_it_is_reported_by_path(self, tmp_path: Path):
        root = _package(tmp_path, app="def build(item: int) -> None: ...\n")

        assert modules_evaluating_their_annotations(root, [root / "someapp"]) == ["someapp/app.py"]

    def test_the_import_is_found_under_a_docstring(self, tmp_path: Path):
        root = _package(tmp_path, app='"""What this does."""\n' + DEFERRED)

        assert modules_evaluating_their_annotations(root, [root / "someapp"]) == []

    def test_a_module_with_no_annotations_anywhere_still_has_to_defer(self, tmp_path: Path):
        # The rule is the file's, not the signature's: an exemption that depends
        # on today's contents expires the first time someone adds a parameter.
        root = _package(tmp_path, app="VALUE = 3\n")

        assert modules_evaluating_their_annotations(root, [root / "someapp"]) == ["someapp/app.py"]

    def test_a_future_import_of_something_else_does_not_count(self, tmp_path: Path):
        root = _package(tmp_path, app="from __future__ import division\n")

        assert modules_evaluating_their_annotations(root, [root / "someapp"]) == ["someapp/app.py"]

    def test_an_empty_module_is_left_alone(self, tmp_path: Path):
        # `__init__.py` files that exist only to make a package are the bulk of
        # these, and there is nothing in one for a version to disagree about.
        root = _package(tmp_path, __init__="", app=DEFERRED)

        assert modules_evaluating_their_annotations(root, [root / "someapp"]) == []


def test_the_assertion_names_every_one_and_the_command_that_fixes_them(tmp_path: Path):
    root = _package(tmp_path, app="X: int = 1\n")

    with pytest.raises(AssertionError, match=r"someapp/app\.py(.|\n)*ruff"):
        assert_every_module_defers_annotations(root, [root / "someapp"])


def test_every_module_in_this_repo_defers_its_annotations():
    root = Path(__file__).resolve().parent.parent
    assert_every_module_defers_annotations(root, [root / "app_support", root / "tests"])

"""A read of another object's private name, through any handle. Every module here is invented."""
from __future__ import annotations

from pathlib import Path

import pytest

from app_support.private_reach import private_imports, reaches_in


def _reaches(source: str) -> list[str]:
    return [reach.written for reach in reaches_in(source)]


class TestThroughAHandle:
    @pytest.mark.parametrize("source", [
        "class View:\n    def f(self):\n        return self._pane._rows\n",
        "class View:\n    def f(self):\n        return self.pane._rows\n",
        "class View:\n    def f(self):\n        pane = self._pane\n        return pane._rows\n",
        "class View:\n    def f(self):\n        a = self._pane\n        b = a\n        return b._rows\n",
        "class View:\n    def f(self):\n        pane: object = self._pane\n        return pane._rows\n",
        "class View:\n    def f(self):\n        return (pane := self._pane)._rows\n",
        "def f(pane):\n    return pane._rows\n",
        "def f(pane):\n    pane._rows = 1\n",
        "def f():\n    return make_pane()._rows\n",
        "def f(pane):\n    return getattr(pane, '_rows')\n",
        "def f(pane):\n    setattr(pane, '_rows', 1)\n",
        "import panes\n\n\ndef f():\n    return panes._rows\n",
    ], ids=["private handle", "public handle", "alias", "alias of an alias", "annotated alias", "walrus",
            "parameter", "write", "returned", "getattr", "setattr", "module"])
    def test_each_shape_is_one_reach(self, source: str):
        assert len(_reaches(source)) == 1, source

    def test_the_reach_says_where_and_what(self):
        reach = reaches_in("def f(pane):\n    return pane._rows\n")[0]

        assert (reach.line, reach.written) == (2, "pane._rows")


class TestAClassesOwnPrivates:
    @pytest.mark.parametrize("source", [
        "class View:\n    def f(self):\n        return self._rows\n",
        "class View:\n    @classmethod\n    def f(cls):\n        return cls._rows\n",
        "class View:\n    def f(this):\n        return this._rows\n",
        "class View:\n    def f(self):\n        me = self\n        again = me\n        return again._rows\n",
        "class View:\n    def f(self):\n        def inner():\n            return self._rows\n        return inner\n",
        "class View:\n    def f(self):\n        return super()._rows\n",
        "class View:\n    def f(self):\n        return type(self)._rows\n",
        "class View:\n    def f(self):\n        return self.__class__._rows\n",
        "class View:\n    def f(self):\n        return View._rows\n",
        "class View:\n    @classmethod\n    def f(cls):\n        made = cls()\n        made._rows = 1\n        return made\n",
        "class View:\n    def f(self):\n        twin = View()\n        twin._rows = 1\n",
        "class View:\n    def f(self, other: 'View'):\n        return other._rows\n",
        "class View:\n    def f(self, other: View):\n        return other._rows\n",
        "class View:\n    def __eq__(self, other):\n        return other._rows == self._rows\n",
        "class View:\n    def f(self):\n        return getattr(self, '_rows')\n",
        "class View:\n    def f(self, a):\n        self._rows, self._cols = a\n",
    ], ids=["self", "cls", "any first name", "alias of self", "closure", "super", "type", "__class__", "class name",
            "cls made", "class made", "annotated", "annotated, quoted", "comparison", "getattr", "unpacked into"])
    def test_none_of_these_is_a_reach(self, source: str):
        assert _reaches(source) == [], source

    @pytest.mark.parametrize("source", [
        "def f(self):\n    return self._rows\n",
        "class View:\n    @staticmethod\n    def f(self):\n        return self._rows\n",
        "class View:\n    def f(self, other):\n        me = self\n        me = other\n        return me._rows\n",
        "class View:\n    def f(self, other):\n        self = other\n        return self._rows\n",
        "class View:\n    def f(self):\n        me, _ = self, 1\n        return me._rows\n",
        "class View:\n    def f(self):\n        def inner(self):\n            return self._rows\n        return inner\n",
        "class View:\n    def __init__(self, other):\n        self.rows = other._rows\n",
        "class View:\n    def f(self, other: 'Pane'):\n        return other._rows\n",
        "class View:\n    def f(self, others):\n        *self, _ = others\n        return self._rows\n",
        "class View:\n    def f(self, others):\n        for self in others:\n            self._rows\n",
        "class View:\n    def f(self, other):\n        with other as self:\n            self._rows\n",
        "class View:\n    def f(self):\n        return lambda self: self._rows\n",
    ], ids=["a free function's self", "a static method's self", "rebound to another", "self rebound",
            "unpacked", "a closure's own self", "a constructor's parameter", "annotated as another class",
            "starred", "looped over", "with", "a lambda's own self"])
    def test_a_name_that_only_looks_like_self_is_a_reach(self, source: str):
        assert len(_reaches(source)) == 1, source


class TestWhatTheUnderscoreDoesNotMean:
    @pytest.mark.parametrize("source", [
        "def f(row):\n    return row._replace(a=1)\n",
        "def f(row):\n    return row._asdict()\n",
        "def f(row):\n    return row._fields\n",
        "def f(row):\n    return row._make([1])\n",
        "def f(row):\n    return row._field_defaults\n",
        "import os\n\n\ndef f():\n    os._exit(0)\n",
        "import sys\n\n\ndef f():\n    return sys._getframe()\n",
        "import sys\n\n\ndef f():\n    return sys._MEIPASS\n",
        "def f(thing):\n    return thing.__dict__\n",
        "def f(thing):\n    return thing._fields_\n",
    ], ids=["_replace", "_asdict", "_fields", "_make", "_field_defaults", "os._exit", "sys._getframe", "sys._MEIPASS",
            "a dunder", "a ctypes declaration"])
    def test_a_name_the_standard_library_publishes_is_no_reach(self, source: str):
        assert _reaches(source) == [], source

    def test_a_name_published_by_one_module_is_private_on_another(self):
        assert _reaches("def f(os):\n    os._exit_soon(0)\n") == ["os._exit_soon"]


def _charged(root: Path, **modules: str) -> dict[str, list[str]]:
    for dotted, text in modules.items():
        path = root.joinpath(*dotted.split("__")).with_suffix(".py")
        path = path.with_stem("__init__") if path.stem == "init" else path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return private_imports(sorted(root.rglob("*.py")), root)


class TestWhatAnImportCharges:
    def test_a_private_name_imported_is_charged(self, tmp_path: Path):
        assert _charged(tmp_path, a="_x = 1\n", b="from a import _x\n") == {"b.py": ["b.py:1: _x of a"]}

    def test_renaming_it_on_the_way_in_changes_nothing(self, tmp_path: Path):
        assert _charged(tmp_path, a="_x = 1\n", b="from a import _x as x\n") == {"b.py": ["b.py:1: _x of a"]}

    def test_a_module_of_another_repo_is_charged_as_well(self, tmp_path: Path):
        assert _charged(tmp_path, b="from sibling.thing import _x\n") == {
            "b.py": ["b.py:1: _x of sibling.thing"]}

    def test_a_public_name_is_not(self, tmp_path: Path):
        assert _charged(tmp_path, a="x = 1\n", b="from a import x\n") == {}

    def test_a_public_name_a_barrel_hands_on_from_a_private_one_is_charged_to_its_definer(self, tmp_path: Path):
        charged = _charged(tmp_path, pkg__init="from pkg.impl import _x as x\n", pkg__impl="_x = 1\n",
                           user="from pkg import x\n")

        assert charged["user.py"] == ["user.py:1: _x of pkg.impl, as x of pkg"]

    def test_a_barrel_of_a_barrel_is_followed(self, tmp_path: Path):
        charged = _charged(tmp_path, top="from middle import y as z\n", middle="from impl import _x as y\n",
                           impl="_x = 1\n", user="from top import z\n")

        assert charged["user.py"] == ["user.py:1: _x of impl, as z of top"]

    def test_a_relative_import_is_followed(self, tmp_path: Path):
        charged = _charged(tmp_path, pkg__init="from .impl import _x as x\n", pkg__impl="_x = 1\n",
                           pkg__user="from . import x\n")

        assert charged["pkg/user.py"] == ["pkg/user.py:1: _x of pkg.impl, as x of pkg"]

    def test_a_barrels_name_read_off_the_module_is_charged(self, tmp_path: Path):
        charged = _charged(tmp_path, barrel="from impl import _x as x\n", impl="_x = 1\n",
                           user="import barrel\n\n\ndef f():\n    return barrel.x\n")

        assert charged["user.py"] == ["user.py:5: _x of impl, as x of barrel"]

    def test_a_barrels_name_read_off_a_renamed_module_is_charged(self, tmp_path: Path):
        charged = _charged(tmp_path, pkg__barrel="from impl import _x as x\n", impl="_x = 1\n",
                           user="import pkg.barrel as b\n\n\ndef f():\n    return b.x\n")

        assert charged["user.py"] == ["user.py:5: _x of impl, as x of pkg.barrel"]

    def test_a_cycle_of_barrels_ends(self, tmp_path: Path):
        assert _charged(tmp_path, a="from b import x\n", b="from a import x\n") == {}

    def test_a_private_module_is_charged_from_outside_its_package(self, tmp_path: Path):
        charged = _charged(tmp_path, pkg___impl="x = 1\n", user="from pkg._impl import x\n", other="import pkg._impl\n")

        assert charged == {"other.py": ["other.py:1: pkg._impl"], "user.py": ["user.py:1: pkg._impl"]}

    def test_a_private_module_is_not_charged_from_inside_its_package(self, tmp_path: Path):
        assert _charged(tmp_path, pkg___impl="x = 1\n", pkg__user="from pkg._impl import x\n",
                        pkg__rel="from ._impl import x\n", pkg__mod="from . import _impl\n") == {}

    def test_a_private_module_imported_by_name_from_outside_is_charged(self, tmp_path: Path):
        assert _charged(tmp_path, pkg___impl="x = 1\n", user="from pkg import _impl\n") == {
            "user.py": ["user.py:1: _impl of pkg"]}

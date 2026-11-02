"""Tests for the family's coupling counter. Every class, module and name here is invented."""
from __future__ import annotations

from pathlib import Path
from textwrap import dedent

import pytest

from app_support.coupling import Measured, assert_no_app_imports_another, measure
from app_support.coupling.classes import measure_classes
from app_support.coupling.doubles import Doubles, count_doubles
from app_support.coupling.imports import ModuleTree, another_apps_imports
from app_support.gates import Checkout


def _surface(source: str, name: str = "Pane"):
    return measure_classes(dedent(source))[name]


class TestReachThroughChains:
    @pytest.mark.parametrize(("body", "chains", "longest"), [
        ("self.a", 0, 0),
        ("self.a.b", 1, 2),
        ("self.a.b.c()", 1, 3),
        ("x = self.a\n        x.b", 1, 2),
        ("x = self.a.b\n        x.c", 2, 3),
        ("x: object = self.a\n        x.b", 1, 2),
        ("if (x := self.a):\n            x.b", 1, 2),
        ("x = y = self.a\n        y.b\n        x.b", 2, 2),
        ("x, y = self.a, self.b\n        y.c", 1, 2),
        ("with self.a as x:\n            x.b", 1, 2),
        ("me = self\n        me.a.b", 1, 2),
        ("x = self.a\n        x = 1\n        x.b", 0, 0),
        ("x = self.a\n        go = lambda: x.b", 1, 2),
        ("self.a.b().c", 1, 2),
        ("other.a.b", 0, 0),
    ])
    def test_a_chain_is_counted_through_any_local_it_is_handed_to(self, body, chains, longest):
        surface = _surface(f"""\
            class Pane:
                def show(self, other):
                    {body.replace(chr(10) + "        ", chr(10) + "                    ")}
            """)

        assert (surface.chains, surface.longest_chain) == (chains, longest)


class TestWhatAClassIsMadeOf:
    def test_its_methods_include_those_inside_a_block_and_leave_out_a_nested_classs(self):
        surface = _surface("""\
            class Pane:
                def one(self): pass
                async def two(self): pass
                if True:
                    def three(self): pass
                try:
                    def four(self): pass
                except OSError:
                    pass
                class Inner:
                    def five(self): pass
            """)

        assert surface.methods == 4

    def test_its_attributes_are_what_its_body_and_its_methods_bind(self):
        surface = _surface("""\
            class Pane:
                __slots__ = ()
                kind = 1
                size: int = 2
                def __init__(self, other):
                    self.a = 1
                    self.b: int = 2
                    self.a += 1
                    self.c, self.d = 3, 4
                    me = self
                    me.e = 5
                    other.f = 6
                    self.a.g = 7
            """)

        assert surface.attributes == 7

    def test_two_classes_of_one_name_are_told_apart_by_what_holds_them(self):
        measured = measure_classes(dedent("""\
            class Outer:
                class Inner:
                    def one(self): pass
                def make(self):
                    class Inner:
                        def one(self): pass
                        def two(self): pass
                    return Inner
            """))

        assert measured["Outer.Inner"].methods == 1
        assert measured["Outer.make.Inner"].methods == 2


class TestFanOut:
    def test_it_counts_each_module_of_the_repo_once_however_it_is_imported(self):
        tree = ModuleTree({
            "pkg/__init__.py": "",
            "pkg/one.py": "",
            "pkg/two.py": "x = 1\n",
            "pkg/three.py": "",
            "pkg/user.py": ("import os\nimport pkg.one\nimport pkg.one as again\nfrom pkg import two\n"
                            "from . import three\n\n\ndef later():\n    from .two import x\n"),
        })

        assert tree.fan_out()["pkg/user.py"] == 3

    def test_a_name_taken_through_a_package_counts_against_the_module_that_defines_it(self):
        tree = ModuleTree({
            "pkg/__init__.py": "from pkg.real import shown\nfrom pkg.other import also\n",
            "pkg/real.py": "shown = 1\n",
            "pkg/other.py": "also = 1\n",
            "user.py": "from pkg import shown\n",
        })

        assert tree.fan_out()["user.py"] == 1

    def test_a_package_that_only_gathers_names_reaches_for_nothing_itself(self):
        tree = ModuleTree({
            "pkg/__init__.py": 'from pkg.real import shown\n__all__ = ["shown"]\n',
            "pkg/real.py": "shown = 1\n",
        })

        assert tree.fan_out()["pkg/__init__.py"] == 0

    def test_a_module_does_not_count_itself(self):
        assert ModuleTree({"solo.py": "import solo\n"}).fan_out()["solo.py"] == 0


class TestMutablesImportedAcrossModules:
    @pytest.mark.parametrize("value", [
        "[]", "{}", "{1}", "[n for n in ()]", "{n: 1 for n in ()}", "list()", "dict()", "set()",
        "defaultdict(list)", "collections.deque()", "Counter()", "OrderedDict()",
    ])
    def test_a_mutable_container_taken_by_another_module_is_counted(self, value):
        tree = ModuleTree({"held.py": f"TABLE = {value}\n", "user.py": "from held import TABLE\n"})

        assert tree.mutables_imported() == {"held.py": 1}

    @pytest.mark.parametrize("value", ["()", "1", "'a'", "frozenset()", "make()", "MappingProxyType({})"])
    def test_anything_else_is_not(self, value):
        tree = ModuleTree({"held.py": f"TABLE = {value}\n", "user.py": "from held import TABLE\n"})

        assert tree.mutables_imported() == {}

    @pytest.mark.parametrize("user", [
        "import pkg.held as held\nheld.TABLE\n",
        "import pkg.held\npkg.held.TABLE\n",
        "from pkg import held\nheld.TABLE\n",
        "from pkg import held as h\nh.TABLE\n",
        "from pkg.held import TABLE\n",
        "from pkg.held import TABLE as T\n",
        "from pkg import TABLE\n",
        "def later():\n    from pkg.held import TABLE\n",
    ])
    def test_it_is_followed_through_any_spelling_of_the_import(self, user):
        tree = ModuleTree({
            "pkg/__init__.py": "from pkg.held import TABLE\n",
            "pkg/held.py": "TABLE: dict = {}\n",
            "user.py": user,
        })

        assert tree.mutables_imported() == {"pkg/held.py": 1}

    def test_two_takers_of_one_container_are_one_container(self):
        tree = ModuleTree({"held.py": "TABLE = []\n", "one.py": "from held import TABLE\n",
                           "two.py": "from held import TABLE\n"})

        assert tree.mutables_imported() == {"held.py": 1}

    def test_a_module_using_its_own_is_not_taking_it_from_another(self):
        assert ModuleTree({"held.py": "TABLE = []\nTABLE.append(1)\n"}).mutables_imported() == {}

    def test_one_bound_under_a_block_is_still_the_modules(self):
        tree = ModuleTree({"held.py": "try:\n    TABLE = []\nexcept OSError:\n    pass\n",
                           "user.py": "from held import TABLE\n"})

        assert tree.mutables_imported() == {"held.py": 1}


class TestOneAppImportingAnother:
    @pytest.mark.parametrize("source", [
        "import fun_time\n",
        "import fun_time.dashboard as d\n",
        "from fun_time.dashboard import x\n",
        "def later():\n    import fun_time\n",
        "import importlib\nimportlib.import_module('fun_time.dashboard')\n",
        "__import__('fun_time')\n",
    ])
    def test_any_way_of_importing_it_is_found(self, source):
        assert another_apps_imports({"mine.py": source}, own=("origenerator",)) == {"mine.py": 1}

    @pytest.mark.parametrize("source", [
        "import os\n", "import shared_ui.theme\n", "from . import fun_time\n", "fun_time = 1\n",
        "import origenerator.gui\n",
    ])
    def test_its_own_a_library_and_a_relative_import_are_not_that(self, source):
        assert another_apps_imports({"mine.py": source}, own=("origenerator",)) == {}


def _doubles(source: str, own=("mine",)) -> Doubles:
    return count_doubles(dedent(source), own=own)


class TestDoubleCounts:
    @pytest.mark.parametrize("source", [
        "from unittest.mock import MagicMock\nMagicMock()\n",
        "from unittest.mock import Mock\nMock()\n",
        "from unittest.mock import AsyncMock\nAsyncMock()\n",
        "from unittest.mock import MagicMock as M\nM()\n",
        "from unittest import mock\nmock.MagicMock()\n",
        "import unittest.mock\nunittest.mock.Mock()\n",
        "import unittest.mock as um\num.Mock()\n",
        "from unittest.mock import patch, Mock\npatch('a.b', new_callable=Mock)\n",
    ])
    def test_a_mock_is_counted_under_any_name_it_is_imported_by(self, source):
        assert _doubles(source).mocks == 1

    def test_a_mock_named_only_to_annotate_is_not_a_mock(self):
        assert _doubles("from unittest.mock import Mock\ndef f(x: Mock) -> Mock:\n    pass\n").mocks == 0

    def test_a_class_of_our_own_with_that_name_is_not_a_mock(self):
        assert _doubles("class Mock:\n    pass\nMock()\n").mocks == 0

    @pytest.mark.parametrize("source", [
        "from unittest.mock import patch\npatch('a.b')\n",
        "from unittest.mock import patch\n@patch('a.b')\ndef f(): pass\n",
        "from unittest.mock import patch\npatch.object(thing, 'b')\n",
        "from unittest.mock import patch\npatch.dict('a.b', {})\n",
        "from unittest.mock import patch as swap\nswap('a.b')\n",
        "from unittest import mock\nwith mock.patch('a.b'):\n    pass\n",
        "from unittest.mock import patch\nswap = patch.object\nswap(thing, 'b')\n",
    ])
    def test_a_patch_is_counted_under_any_name_it_is_reached_by(self, source):
        assert _doubles(source).patches == 1

    @pytest.mark.parametrize("source", [
        "def test(monkeypatch):\n    monkeypatch.setattr('a.b', 1)\n",
        "def test(monkeypatch):\n    swap = monkeypatch.setattr\n    swap('a.b', 1)\n",
        "def test(monkeypatch):\n    mp = monkeypatch\n    mp.setattr('a.b', 1)\n",
        "import pytest\ndef test(mp: pytest.MonkeyPatch):\n    mp.setattr('a.b', 1)\n",
        "import pytest\nwith pytest.MonkeyPatch.context() as mp:\n    mp.setattr('a.b', 1)\n",
        "import pytest\nmp = pytest.MonkeyPatch()\nmp.setattr('a.b', 1)\n",
    ])
    def test_a_monkeypatch_is_counted_under_any_name_it_is_handed_to(self, source):
        assert _doubles(source).monkeypatches == 1

    def test_a_monkeypatch_setting_the_environment_is_no_replacement_of_code(self):
        assert _doubles("def test(monkeypatch):\n    monkeypatch.setenv('A', '1')\n").monkeypatches == 0

    @pytest.mark.parametrize("source", [
        "from types import SimpleNamespace\nSimpleNamespace(a=1)\n",
        "from types import SimpleNamespace as NS\nNS(a=1)\n",
        "import types\ntypes.SimpleNamespace(a=1)\n",
        "from types import SimpleNamespace\nbag = SimpleNamespace\nbag(a=1)\n",
    ])
    def test_a_simple_namespace_bag_is_counted_under_any_name(self, source):
        doubles = _doubles(source)

        assert doubles.simple_namespaces == 1


class TestPatchingALibrarysInsides:
    @pytest.mark.parametrize("source", [
        "from unittest.mock import patch\npatch('shared_ui.theme.COLOR')\n",
        "from unittest.mock import patch\nimport shared_ui.theme\npatch.object(shared_ui.theme, 'COLOR')\n",
        "from unittest.mock import patch\nfrom shared_ui import theme\npatch.object(theme, 'COLOR')\n",
        "from unittest.mock import patch\nfrom shared_ui.theme import Palette as P\npatch.object(P, 'color')\n",
        "from unittest.mock import patch\nTARGET = 'voice_core.listen.start'\npatch(TARGET)\n",
        "from unittest.mock import patch\npatch(f'app_support.state_files.{name}')\n",
        "def test(monkeypatch):\n    monkeypatch.setattr('funestra.engine.play', None)\n",
        "import funestra.engine as e\ndef test(monkeypatch):\n    monkeypatch.setattr(e, 'play', None)\n",
        "def test(monkeypatch):\n    monkeypatch.delattr('funestra.engine.play')\n",
        "from funestra import TABLE\ndef test(monkeypatch):\n    monkeypatch.setitem(TABLE, 'a', 1)\n",
    ])
    def test_a_target_inside_a_library_is_counted_however_it_is_spelled(self, source):
        assert _doubles(source).library_patches == 1

    @pytest.mark.parametrize("source", [
        "from unittest.mock import patch\npatch('mine.module.thing')\n",
        "from unittest.mock import patch\npatch('os.getcwd')\n",
        "from unittest.mock import patch\npatch('shared_ui.testing.helper')\n",
        "from unittest.mock import patch\nfrom shared_ui import testing\npatch.object(testing, 'helper')\n",
        "from unittest.mock import patch\npatch.object(local_thing, 'x')\n",
        "def test(monkeypatch):\n    monkeypatch.setenv('shared_ui.theme', '1')\n",
    ])
    def test_its_own_code_the_standard_library_and_a_librarys_testing_module_are_not_that(self, source):
        assert _doubles(source).library_patches == 0

    def test_a_library_patching_itself_is_replacing_its_own_code(self):
        assert _doubles("from unittest.mock import patch\npatch('shared_ui.theme.X')\n",
                        own=("shared_ui",)).library_patches == 0

    def test_a_funestra_checkouts_old_import_names_are_funestras(self):
        assert _doubles("from unittest.mock import patch\npatch('player_core.engine.X')\n").library_patches == 1


A_BIG_CLASS = "class Big:\n" + "".join(f"    def m{n}(self):\n        return self.a.b\n" for n in range(31))


def _checkout(root: Path, files: dict[str, str]) -> Checkout:
    (root / "pyproject.toml").write_text('[project]\nname = "someapp"\n', encoding="utf-8")
    for name, text in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return Checkout(root)


class TestMeasuringACheckout:
    def test_its_code_gives_the_code_counts_and_its_tests_the_doubles(self, tmp_path):
        measured = measure(_checkout(tmp_path, {
            "someapp/__init__.py": "",
            "someapp/held.py": "TABLE = []\n",
            "someapp/user.py": ("from someapp.held import TABLE\n\n\nclass Pane:\n"
                                "    def show(self):\n        return self.a.b\n"),
            "tests/test_user.py": ("from types import SimpleNamespace\nfrom unittest.mock import MagicMock, patch\n"
                                   "MagicMock()\npatch('shared_ui.theme.X')\nSimpleNamespace()\n"
                                   "def test(monkeypatch):\n    monkeypatch.setattr('a.b', 1)\n"),
        }))

        assert measured.per_file == {
            "reach_chains": {"someapp/user.py": 1}, "mutables_imported": {"someapp/held.py": 1},
            "mocks": {"tests/test_user.py": 1}, "patches": {"tests/test_user.py": 1},
            "monkeypatches": {"tests/test_user.py": 1}, "simple_namespaces": {"tests/test_user.py": 1},
            "library_patches": {"tests/test_user.py": 1}}

    def test_a_class_or_a_file_over_a_limit_is_named_with_what_it_is_over(self, tmp_path):
        measured = measure(_checkout(tmp_path, {
            "someapp/__init__.py": "",
            "someapp/big.py": A_BIG_CLASS,
            "someapp/long.py": "x = 1\n" * 301,
            "someapp/wide.py": "".join(f"import someapp.m{n}\n" for n in range(16)),
            **{f"someapp/m{n}.py": "" for n in range(16)},
        }))

        assert measured.over_the_limits == {
            "someapp/big.py::Big::methods": 31, "someapp/big.py::Big::chains": 31,
            "someapp/long.py::statements": 301,
            "someapp/wide.py::fan-out": 16,
        }

    def test_a_chain_too_long_is_named_by_its_length(self, tmp_path):
        measured = measure(_checkout(tmp_path, {
            "someapp/__init__.py": "",
            "someapp/deep.py": "class Deep:\n    def go(self):\n        return self.a.b.c.d\n",
        }))

        assert measured.over_the_limits == {"someapp/deep.py::Deep::chain-length": 4}

    def test_an_app_reaching_for_another_is_found_in_its_code_and_its_tests(self, tmp_path):
        measured = measure(_checkout(tmp_path, {
            "someapp/__init__.py": "import origenerator\n",
            "tests/test_it.py": "from fun_time import x\n",
        }))

        assert measured.another_apps_imports == {"someapp/__init__.py": 1, "tests/test_it.py": 1}


class TestAnotherAppsCode:
    def test_another_app_imported_is_refused_whatever_the_numbers_say(self):
        with pytest.raises(AssertionError, match=r"a.py imports another app"):
            assert_no_app_imports_another(Measured(another_apps_imports={"a.py": 1}))

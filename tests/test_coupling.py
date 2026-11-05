from __future__ import annotations

from pathlib import Path
from textwrap import dedent

import pytest

from app_support.coupling import assert_no_app_imports_another, measured_sections
from app_support.coupling.imports import ModuleTree, another_apps_imports
from app_support.coupling.library_patches import library_patches_in
from app_support.gates import Checkout, baseline


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


def _library_patches(source: str, own=("mine",)) -> int:
    return library_patches_in(dedent(source), own=own)


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
        "from unittest.mock import patch as swap\nswap('shared_ui.theme.COLOR')\n",
        "from unittest import mock\nwith mock.patch('shared_ui.theme.COLOR'):\n    pass\n",
        "from unittest.mock import patch\nswap = patch.object\nimport shared_ui.theme\nswap(shared_ui.theme, 'COLOR')\n",
        "from unittest.mock import patch\n@patch('shared_ui.theme.COLOR')\ndef f(): pass\n",
        "from unittest.mock import patch\npatch.dict('shared_ui.theme.TABLE', {})\n",
        "def test(monkeypatch):\n    swap = monkeypatch.setattr\n    swap('funestra.engine.play', None)\n",
        "def test(monkeypatch):\n    mp = monkeypatch\n    mp.setattr('funestra.engine.play', None)\n",
        "import pytest\ndef test(mp: pytest.MonkeyPatch):\n    mp.setattr('funestra.engine.play', None)\n",
        "import pytest\nwith pytest.MonkeyPatch.context() as mp:\n    mp.setattr('funestra.engine.play', None)\n",
        "import pytest\nmp = pytest.MonkeyPatch()\nmp.setattr('funestra.engine.play', None)\n",
    ])
    def test_a_target_inside_a_library_is_counted_however_it_is_spelled(self, source):
        assert _library_patches(source) == 1

    @pytest.mark.parametrize("source", [
        "from unittest.mock import patch\npatch('mine.module.thing')\n",
        "from unittest.mock import patch\npatch('os.getcwd')\n",
        "from unittest.mock import patch\npatch('shared_ui.testing.helper')\n",
        "from unittest.mock import patch\nfrom shared_ui import testing\npatch.object(testing, 'helper')\n",
        "from unittest.mock import patch\npatch.object(local_thing, 'x')\n",
        "def test(monkeypatch):\n    monkeypatch.setenv('shared_ui.theme', '1')\n",
    ])
    def test_its_own_code_the_standard_library_and_a_librarys_testing_module_are_not_that(self, source):
        assert _library_patches(source) == 0

    def test_a_library_patching_itself_is_replacing_its_own_code(self):
        assert _library_patches("from unittest.mock import patch\npatch('shared_ui.theme.X')\n", own=("shared_ui",)) == 0

    def test_a_funestra_checkouts_old_import_names_are_funestras(self):
        assert _library_patches("from unittest.mock import patch\npatch('player_core.engine.X')\n") == 1

    def test_a_patch_of_our_own_making_with_that_name_is_not_one(self):
        assert _library_patches("def patch(target): pass\npatch('shared_ui.theme.X')\n") == 0


def _checkout(root: Path, files: dict[str, str]) -> Checkout:
    (root / "pyproject.toml").write_text('[project]\nname = "someapp"\n', encoding="utf-8")
    for name, text in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return Checkout(root)


class TestMeasuringACheckout:
    def test_its_code_gives_the_mutables_and_its_tests_the_library_patches_each_per_file(self, tmp_path):
        measured = measured_sections(_checkout(tmp_path, {
            "someapp/__init__.py": "",
            "someapp/held.py": "TABLE = []\n",
            "someapp/user.py": "from someapp.held import TABLE\n",
            "tests/test_user.py": "from unittest.mock import patch\npatch('shared_ui.theme.X')\n",
            "tests/test_other.py": "from unittest.mock import patch\npatch('someapp.held.TABLE')\n",
        }))

        assert measured == {"mutables_imported": {"someapp/held.py": 1}, "library_patches": {"tests/test_user.py": 1}}


class TestOneAppImportingAnotherFromACheckout:
    def test_it_is_refused_in_its_code_and_its_tests(self, tmp_path):
        checkout = _checkout(tmp_path, {
            "someapp/__init__.py": "import origenerator\n",
            "tests/test_it.py": "from fun_time import x\n",
        })

        with pytest.raises(AssertionError, match=r"someapp/__init__\.py imports another app.*tests/test_it\.py"):
            assert_no_app_imports_another(checkout)

    def test_a_checkout_that_keeps_to_itself_passes(self, tmp_path):
        assert_no_app_imports_another(_checkout(tmp_path, {"someapp/__init__.py": "import shared_ui\n"}))


class TestTheBaselineHoldsWhatIsCounted:
    A_TEST = "from unittest.mock import patch\npatch('shared_ui.theme.X')\n"

    def _adopted(self, root: Path) -> Checkout:
        checkout = _checkout(root, {"someapp/__init__.py": "", "tests/test_one.py": self.A_TEST})
        baseline.main_in(checkout, said=lambda _line: None)
        return checkout

    def test_adopting_writes_what_it_measures(self, tmp_path):
        assert self._adopted(tmp_path).sections["library_patches"] == {"tests/test_one.py": 1}

    def test_a_library_patch_added_to_a_file_is_refused_though_another_file_lost_one(self, tmp_path):
        checkout = self._adopted(tmp_path)
        (tmp_path / "tests/test_one.py").write_text("", encoding="utf-8")
        (tmp_path / "tests/test_two.py").write_text(self.A_TEST, encoding="utf-8")

        with pytest.raises(AssertionError, match=r"tests/test_two\.py holds 1 library_patches, over its entry of 0"):
            baseline.assert_count_holds(checkout, baseline.count_named("library_patches"))

    def test_a_container_another_module_starts_importing_is_refused(self, tmp_path):
        checkout = self._adopted(tmp_path)
        (tmp_path / "someapp/held.py").write_text("TABLE = []\n", encoding="utf-8")
        (tmp_path / "someapp/user.py").write_text("from someapp.held import TABLE\n", encoding="utf-8")

        with pytest.raises(AssertionError, match=r"someapp/held\.py holds 1 mutables_imported, over its entry of 0"):
            baseline.assert_count_holds(checkout, baseline.count_named("mutables_imported"))

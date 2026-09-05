"""The undeclared-dependency gate: what counts as third-party, what a pyproject
declares, and what is left over.  Every package and dependency here is invented."""
from __future__ import annotations

from pathlib import Path

import pytest

from app_support.dependencies import (
    assert_every_import_is_declared,
    declared_dependencies,
    third_party_imports,
    undeclared_imports,
)


def _repo(tmp_path: Path, *, source: str, dependencies: str = '["examplelib>=1", "Other_Thing"]') -> Path:
    package = tmp_path / "someapp"
    package.mkdir()
    (package / "__init__.py").write_text("", encoding="utf-8")
    (package / "app.py").write_text(source, encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text(
        f'[project]\nname = "someapp"\ndependencies = {dependencies}\n', encoding="utf-8")
    return tmp_path


class TestDeclaredDependencies:
    def test_names_are_read_off_the_requirement_and_normalized(self, tmp_path: Path):
        root = _repo(tmp_path, source="", dependencies='["examplelib>=1.2", "Other_Thing[extra]", "third ; sys_platform == \'win32\'"]')

        assert declared_dependencies(root / "pyproject.toml") == {"examplelib", "other-thing", "third"}

    def test_an_extra_is_a_declaration_too(self, tmp_path: Path):
        # A feature behind `pip install repo[voice]` is declared; installing it is
        # the launcher's business.
        root = _repo(tmp_path, source="")
        pyproject = (
            "[project]\n"
            'name = "someapp"\n'
            'dependencies = ["examplelib"]\n'
            "[project.optional-dependencies]\n"
            'voice = ["speechlib>=2"]\n'
        )
        (root / "pyproject.toml").write_text(pyproject, encoding="utf-8")

        assert declared_dependencies(root / "pyproject.toml") == {"examplelib", "speechlib"}


class TestThirdPartyImports:
    def test_the_standard_library_and_the_locals_are_not_third_party(self, tmp_path: Path):
        root = _repo(tmp_path, source="import json\nimport someapp.other\nimport app_support.cli\nimport examplelib\n")

        found = third_party_imports(root, [root / "someapp"], local=("someapp",))

        assert found == {"examplelib": ["someapp/app.py"]}

    def test_an_import_inside_a_try_is_optional_by_construction(self, tmp_path: Path):
        root = _repo(tmp_path, source="try:\n    import maybe_there\nexcept ImportError:\n    maybe_there = None\n")

        assert third_party_imports(root, [root / "someapp"]) == {}

    def test_a_root_level_module_is_scanned_when_named_as_a_file(self, tmp_path: Path):
        root = _repo(tmp_path, source="")
        (root / "tray_app.py").write_text("import examplelib\n", encoding="utf-8")

        found = third_party_imports(root, [root / "someapp", root / "tray_app.py"])

        assert found == {"examplelib": ["tray_app.py"]}

    def test_a_from_import_counts_by_its_top_level_name(self, tmp_path: Path):
        root = _repo(tmp_path, source="from other_thing.sub import x\nfrom . import sibling\n")

        assert third_party_imports(root, [root / "someapp"]) == {"other_thing": ["someapp/app.py"]}


class TestUndeclaredImports:
    def test_a_declared_import_is_not_reported_however_it_is_spelled(self, tmp_path: Path):
        root = _repo(tmp_path, source="import examplelib\nimport other_thing\n")

        assert undeclared_imports(root, [root / "someapp"], root / "pyproject.toml") == []

    def test_an_undeclared_import_is_reported_with_the_file_and_the_pip_name(self, tmp_path: Path):
        root = _repo(tmp_path, source="import PIL\nimport nowhere\n")

        found = undeclared_imports(root, [root / "someapp"], root / "pyproject.toml")

        assert found == ["PIL (pip: pillow) imported by: someapp/app.py",
                         "nowhere (pip: nowhere) imported by: someapp/app.py"]

    def test_a_repos_own_import_name_map_is_read_on_top_of_the_familys(self, tmp_path: Path):
        root = _repo(tmp_path, source="import oddname\n", dependencies='["odd-distribution"]')

        assert undeclared_imports(root, [root / "someapp"], root / "pyproject.toml",
                                  import_names={"oddname": "odd-distribution"}) == []

    def test_the_assertion_names_every_one(self, tmp_path: Path):
        root = _repo(tmp_path, source="import nowhere\n")

        with pytest.raises(AssertionError, match="nowhere"):
            assert_every_import_is_declared(root, [root / "someapp"], root / "pyproject.toml")

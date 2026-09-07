"""The undeclared-dependency gate: what counts as third-party, what a pyproject
declares, and what is left over.  Every package and dependency here is invented."""
from __future__ import annotations

from pathlib import Path

import pytest

from app_support.dependencies import (
    assert_every_dependency_is_bounded,
    assert_every_import_is_declared,
    assert_the_declared_floor_is_the_one_the_gate_runs,
    declared_dependencies,
    third_party_imports,
    unbounded_requirements,
    undeclared_imports,
)


def _repo(tmp_path: Path, *, source: str, dependencies: str = '["examplelib>=1", "Other_Thing"]',
          requires_python: str = ">=3.12") -> Path:
    package = tmp_path / "someapp"
    package.mkdir()
    (package / "__init__.py").write_text("", encoding="utf-8")
    (package / "app.py").write_text(source, encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text(
        f'[project]\nname = "someapp"\nrequires-python = "{requires_python}"\n'
        f"dependencies = {dependencies}\n", encoding="utf-8")
    return tmp_path


class TestDeclaredDependencies:
    def test_names_are_read_off_the_requirement_and_normalized(self, tmp_path: Path):
        root = _repo(tmp_path, source="", dependencies='["examplelib>=1.2", "Other_Thing[extra]", "third ; sys_platform == \'win32\'"]')

        assert declared_dependencies(root / "pyproject.toml") == {"examplelib", "other-thing", "third"}

    def test_an_extra_is_a_declaration_too(self, tmp_path: Path):
        # A feature that needs `pip install repo[voice]` is declared;
        # installing it is the launcher's business.
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


class TestTheDeclaredPythonFloor:
    def _gate(self, root: Path, *versions: str) -> Path:
        jobs = "\n".join(
            f'  job{index}:\n    with:\n      python-version: "{version}"\n'
            for index, version in enumerate(versions))
        workflow = root / "merge-gate.yml"
        workflow.write_text(f"jobs:\n{jobs}", encoding="utf-8")
        return workflow

    def test_the_floor_is_the_lowest_version_the_gate_proves(self, tmp_path: Path):
        root = _repo(tmp_path, source="", requires_python=">=3.12")

        assert_the_declared_floor_is_the_one_the_gate_runs(
            root / "pyproject.toml", self._gate(root, "3.12", "3.14"))

    def test_a_floor_no_run_proves_is_named_with_both_numbers(self, tmp_path: Path):
        # >=3.10 while every leg runs 3.12 says the package installs on a
        # version nothing has ever collected it on.
        root = _repo(tmp_path, source="", requires_python=">=3.10")

        with pytest.raises(AssertionError, match=r"3\.10.*3\.12"):
            assert_the_declared_floor_is_the_one_the_gate_runs(
                root / "pyproject.toml", self._gate(root, "3.12", "3.14"))


class TestUpperBounds:
    def _pyproject(self, tmp_path: Path, body: str) -> Path:
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text('[project]\nname = "someapp"\n' + body, encoding="utf-8")
        return pyproject

    def test_a_ceiling_a_pin_and_a_compatible_release_all_bound_it(self, tmp_path: Path):
        pyproject = self._pyproject(
            tmp_path, 'dependencies = ["a>=1,<2", "b==3.1", "c~=4.2", "d<=5"]\n')

        assert unbounded_requirements(pyproject) == []

    def test_a_bare_name_and_a_floor_alone_are_both_unbounded(self, tmp_path: Path):
        pyproject = self._pyproject(tmp_path, 'dependencies = ["examplelib", "other>=2"]\n')

        assert unbounded_requirements(pyproject) == [
            "examplelib (dependencies)", "other>=2 (dependencies)"]

    def test_an_extra_is_read_and_named_by_its_group(self, tmp_path: Path):
        pyproject = self._pyproject(
            tmp_path,
            'dependencies = []\n[project.optional-dependencies]\nvoice = ["speechlib"]\n')

        assert unbounded_requirements(pyproject) == ["speechlib (voice)"]

    def test_a_marker_does_not_hide_the_missing_ceiling(self, tmp_path: Path):
        requirement = 'winlib ; sys_platform == "win32"'
        pyproject = self._pyproject(tmp_path, f"dependencies = ['{requirement}']\n")

        assert unbounded_requirements(pyproject) == [f"{requirement} (dependencies)"]

    def test_a_name_the_repo_allows_is_left_alone(self, tmp_path: Path):
        pyproject = self._pyproject(tmp_path, 'dependencies = ["examplelib"]\n')

        assert unbounded_requirements(pyproject, allowing=("examplelib",)) == []

    def test_the_assertion_names_every_one(self, tmp_path: Path):
        pyproject = self._pyproject(tmp_path, 'dependencies = ["examplelib"]\n')

        with pytest.raises(AssertionError, match="examplelib"):
            assert_every_dependency_is_bounded(pyproject)


def test_this_repos_declared_floor_is_the_one_its_gate_runs():
    root = Path(__file__).resolve().parent.parent
    assert_the_declared_floor_is_the_one_the_gate_runs(
        root / "pyproject.toml", root / ".github" / "workflows" / "merge-gate.yml")


def test_this_repos_own_requirements_are_bounded():
    assert_every_dependency_is_bounded(Path(__file__).resolve().parent.parent / "pyproject.toml")


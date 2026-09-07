"""Every third-party import a package makes is a dependency its pyproject declares.

A launcher that imports a package nobody declared works on the machine that
happened to have it and dies on the next one -- and on the merge gate, which
installs exactly what the pyproject says.  One repo of eleven had this check;
this is that check, for all of them::

    from app_support.dependencies import assert_every_import_is_declared

    def test_every_third_party_import_is_declared():
        assert_every_import_is_declared(
            ROOT, [ROOT / "the_package"], ROOT / "pyproject.toml",
            local=("the_package",))

An import inside a ``try`` is optional by construction and not counted; the
standard library and the packages named *local* -- the repo's own, and the
siblings installed editable from beside it, which a pyproject deliberately does
not declare -- are not either.  Standard library only.
"""
from __future__ import annotations

import ast
import re
import sys
import tomllib
from collections.abc import Iterable, Mapping
from pathlib import Path

# Import names that differ from the distribution that provides them, across the
# family; a repo adds its own on top.
FAMILY_IMPORT_NAMES: Mapping[str, str] = {
    "serial": "pyserial",
    "cv2": "opencv-python",
    "PIL": "pillow",
    "pygame": "pygame-ce",
    "xr": "pyopenxr",
    "OpenGL": "PyOpenGL",
    "yaml": "PyYAML",
    "mpv": "python-mpv",
    "win32api": "pywin32",
    "win32con": "pywin32",
    "win32gui": "pywin32",
    "win32process": "pywin32",
    "pythoncom": "pywin32",
    "pywintypes": "pywin32",
    "dateutil": "python-dateutil",
    "dotenv": "python-dotenv",
    "sklearn": "scikit-learn",
    "skimage": "scikit-image",
}

# The siblings every repo installs editable from beside it, and never declares.
FAMILY_SIBLINGS = ("app_support", "player_core", "shared_ui")

_DIST_NAME = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)")


def _normalized(name: str) -> str:
    return name.lower().replace("_", "-")


def declared_dependencies(pyproject: Path) -> set[str]:
    """The distributions ``[project.dependencies]`` and every optional extra name, normalized.

    An extra is a declaration too: a feature whose imports need
    ``pip install repo[voice]`` is declared, and installing the feature is the
    launcher's business, not this gate's.
    """
    with Path(pyproject).open("rb") as handle:
        project = tomllib.load(handle).get("project", {})
    requirements = list(project.get("dependencies", []))
    for extra in project.get("optional-dependencies", {}).values():
        requirements.extend(extra)
    found = set()
    for requirement in requirements:
        match = _DIST_NAME.match(requirement)
        if match:
            found.add(_normalized(match.group(1)))
    return found


class _UnconditionalImports(ast.NodeVisitor):
    """The top-level names imported outside any ``try``."""

    def __init__(self) -> None:
        self.names: set[str] = set()

    def visit_Try(self, node: ast.Try) -> None:
        return  # optional by construction

    def visit_Import(self, node: ast.Import) -> None:
        self.names.update(alias.name.split(".")[0] for alias in node.names)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if node.module and node.level == 0:
            self.names.add(node.module.split(".")[0])


def _sources(package: Path) -> list[Path]:
    """*package*'s modules: every ``.py`` under a directory, or the one file named."""
    package = Path(package)
    return [package] if package.is_file() else sorted(package.rglob("*.py"))


def third_party_imports(root: Path, packages: Iterable[Path], *, local: Iterable[str] = ()) -> dict[str, list[str]]:
    """Every third-party name the *packages* import unconditionally, with the files that do.

    A package is a directory, or a single root-level module -- an entry point,
    a config -- named as a file; a repo that keeps modules at its root has both.
    """
    skip = set(sys.stdlib_module_names) | set(local) | set(FAMILY_SIBLINGS)
    found: dict[str, set[str]] = {}
    for package in packages:
        for path in _sources(package):
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))
            except (SyntaxError, UnicodeDecodeError):
                continue
            imports = _UnconditionalImports()
            imports.visit(tree)
            for name in imports.names - skip:
                found.setdefault(name, set()).add(path.relative_to(root).as_posix())
    return {name: sorted(files) for name, files in sorted(found.items())}


def undeclared_imports(
    root: Path, packages: Iterable[Path], pyproject: Path, *,
    local: Iterable[str] = (), import_names: Mapping[str, str] | None = None,
) -> list[str]:
    """One line per third-party import no declared dependency provides."""
    names = {**FAMILY_IMPORT_NAMES, **(import_names or {})}
    declared = declared_dependencies(pyproject)
    return [
        f"{name} (pip: {names.get(name, name)}) imported by: {', '.join(files)}"
        for name, files in third_party_imports(root, packages, local=local).items()
        if _normalized(names.get(name, name)) not in declared
    ]


def assert_every_import_is_declared(
    root: Path, packages: Iterable[Path], pyproject: Path, *,
    local: Iterable[str] = (), import_names: Mapping[str, str] | None = None,
) -> None:
    missing = undeclared_imports(root, packages, pyproject, local=local, import_names=import_names)
    assert not missing, (
        "Third-party imports no [project.dependencies] entry provides:\n  " + "\n  ".join(missing))


_CEILING = re.compile(r"(<|~=|==)")


def _requirements(pyproject: Path) -> list[tuple[str, str]]:
    """Every requirement the project declares, with the group that declares it."""
    with Path(pyproject).open("rb") as handle:
        project = tomllib.load(handle).get("project", {})
    found = [("dependencies", requirement) for requirement in project.get("dependencies", [])]
    for extra, requirements in project.get("optional-dependencies", {}).items():
        found.extend((extra, requirement) for requirement in requirements)
    return found


def unbounded_requirements(pyproject: Path, *, allowing: Iterable[str] = ()) -> list[str]:
    """Every declared requirement that nothing stops from taking a new major version.

    A ceiling, an exact pin and a compatible-release clause all bound one; a bare
    name and a floor alone do not, and both let a Tuesday's release become what
    the next run installs.  *allowing* names the ones a repo has decided to leave
    open, which is a decision that then has a place to be written down.
    """
    exempt = {_normalized(name) for name in allowing}
    return [
        f"{requirement} ({group})"
        for group, requirement in _requirements(pyproject)
        if not _CEILING.search(requirement.split(";")[0])
        and _normalized(_DIST_NAME.match(requirement).group(1)) not in exempt
    ]


def assert_every_dependency_is_bounded(pyproject: Path, *, allowing: Iterable[str] = ()) -> None:
    """No upper bound anywhere means each run installs whatever PyPI serves that morning.

    That is not hypothetical here: the gates installed a major version of the
    imaging stack past the one the developer machines run, and nothing said so.
    """
    unbounded = unbounded_requirements(pyproject, allowing=allowing)
    assert not unbounded, (
        "Requirements with no upper bound, so a new major version lands unasked:\n  "
        + "\n  ".join(unbounded))


_FLOOR = re.compile(r"^>=(\d+)\.(\d+)$")
_GATE_VERSION = re.compile(r'python-version:\s*"(\d+)\.(\d+)"')


def declared_floor(pyproject: Path) -> tuple[int, int]:
    """The ``requires-python`` floor, as (major, minor)."""
    with Path(pyproject).open("rb") as handle:
        declared = tomllib.load(handle).get("project", {}).get("requires-python", "")
    match = _FLOOR.match(declared.strip())
    assert match, f"{pyproject} says requires-python = {declared!r}; the family writes >=X.Y"
    return int(match.group(1)), int(match.group(2))


def proven_floor(workflow: Path) -> tuple[int, int]:
    """The lowest Python any leg of the merge gate runs the suite on.

    Lowest, not first: a gate may run a second, later version to read what it
    says, and what the floor has to match is the oldest one anything is
    actually collected on.
    """
    found = _GATE_VERSION.findall(Path(workflow).read_text(encoding="utf-8"))
    assert found, f"{workflow} names no python-version, so nothing proves a floor"
    return min((int(major), int(minor)) for major, minor in found)


def assert_the_declared_floor_is_the_one_the_gate_runs(pyproject: Path, workflow: Path) -> None:
    """``requires-python`` promises a version; only a run proves one.

    A floor below every version the gate runs is a promise nothing has tested
    and the tree can contradict outright -- syntax or a stdlib module younger
    than the number -- so the two places that state it are held together and
    neither can drift alone.
    """
    declared, proven = declared_floor(pyproject), proven_floor(workflow)
    assert declared == proven, (
        f"{pyproject.name} says >={declared[0]}.{declared[1]} and the gate proves "
        f"{proven[0]}.{proven[1]}; the floor is whatever is actually run")

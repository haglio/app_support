"""What a repo needs is what its pyproject says, in all four of the ways it says it.

A launcher that imports a package nobody declared works on the machine that
happened to have it and dies on the next one -- and on the merge gate, which
installs exactly what the pyproject says.  The same is true of a version nobody
bounded, a sibling checkout nobody recorded, and a Python floor no run proves.
Four gates, adopted a line each::

    from app_support.dependencies import (
        assert_every_dependency_is_bounded, assert_every_import_is_declared,
        assert_every_sibling_is_declared,
        assert_the_declared_floor_is_the_one_the_gate_runs)

    def test_every_third_party_import_is_declared():
        assert_every_import_is_declared(
            ROOT, [ROOT / "the_package"], ROOT / "pyproject.toml",
            local=("the_package",))

    def test_every_requirement_is_bounded():
        assert_every_dependency_is_bounded(ROOT / "pyproject.toml")

    def test_every_sibling_is_declared():
        assert_every_sibling_is_declared(
            ROOT, [ROOT / "the_package", ROOT / "tests"], ROOT / "pyproject.toml")

    def test_the_declared_floor_is_the_one_the_gate_runs():
        assert_the_declared_floor_is_the_one_the_gate_runs(
            ROOT / "pyproject.toml", ROOT / ".github" / "workflows" / "merge-gate.yml")

``assert_every_dependency_is_imported`` is the first gate's converse, for the
dependency nothing reaches for that every install fetches anyway.

An import inside a ``try`` is optional by construction and not counted; the
standard library and the packages named *local* -- the repo's own -- are not
either.  The three siblings are not third-party, because none is published and a
pyproject that named one would send pip to PyPI; they are declared instead in
``[tool.haglio] siblings``, which is what the third gate reads.  Standard
library only.
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


class _TopLevelImports(ast.NodeVisitor):
    """The top-level names a module imports, optionally skipping those in a ``try``."""

    def __init__(self, *, optional: bool = False) -> None:
        self.names: set[str] = set()
        self._optional = optional

    def visit_Try(self, node: ast.Try) -> None:
        if self._optional:
            self.generic_visit(node)

    def visit_Import(self, node: ast.Import) -> None:
        self.names.update(alias.name.split(".")[0] for alias in node.names)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if node.module and node.level == 0:
            self.names.add(node.module.split(".")[0])


def _sources(package: Path) -> list[Path]:
    """*package*'s modules: every ``.py`` under a directory, or the one file named."""
    package = Path(package)
    return [package] if package.is_file() else sorted(package.rglob("*.py"))


def _imported_names(root: Path, packages: Iterable[Path], *,
                    optional: bool = False) -> dict[str, list[str]]:
    """Every top-level name the *packages* import, with the files that do.

    A package is a directory, or a single root-level module -- an entry point,
    a config -- named as a file; a repo that keeps modules at its root has both.
    An import inside a ``try`` is counted only when *optional* is asked for.
    """
    found: dict[str, set[str]] = {}
    for package in packages:
        for path in _sources(package):
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))
            except (SyntaxError, UnicodeDecodeError):
                continue
            imports = _TopLevelImports(optional=optional)
            imports.visit(tree)
            for name in imports.names:
                found.setdefault(name, set()).add(path.relative_to(root).as_posix())
    return {name: sorted(files) for name, files in sorted(found.items())}


def third_party_imports(root: Path, packages: Iterable[Path], *, local: Iterable[str] = ()) -> dict[str, list[str]]:
    """Every third-party name the *packages* import, with the files that do."""
    skip = set(sys.stdlib_module_names) | set(local) | set(FAMILY_SIBLINGS)
    return {name: files for name, files in _imported_names(root, packages).items()
            if name not in skip}


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


def unimported_dependencies(
    root: Path, packages: Iterable[Path], pyproject: Path, *,
    import_names: Mapping[str, str] | None = None, allowing: Iterable[str] = (),
) -> list[str]:
    """Every runtime dependency no module reaches for, fetched by every install anyway.

    The converse of :func:`undeclared_imports`, and the two disagree about a
    ``try`` on purpose: an import inside one is optional by construction and
    needs no declaration, but a package something reaches for *is* used, however
    guarded.  Extras are not read -- a dev extra's test runner is a dependency
    nothing imports by design.
    """
    names = {**FAMILY_IMPORT_NAMES, **(import_names or {})}
    spellings: dict[str, set[str]] = {}
    for imported, distribution in names.items():
        spellings.setdefault(_normalized(distribution), set()).add(imported)
    reached = set(_imported_names(root, packages, optional=True))
    exempt = {_normalized(name) for name in allowing}
    with Path(pyproject).open("rb") as handle:
        declared = tomllib.load(handle).get("project", {}).get("dependencies", [])
    unimported = []
    for requirement in declared:
        distribution = _normalized(_DIST_NAME.match(requirement).group(1))
        if distribution in exempt:
            continue
        if not (spellings.get(distribution, {distribution.replace("-", "_")}) & reached):
            unimported.append(requirement)
    return unimported


def assert_every_dependency_is_imported(
    root: Path, packages: Iterable[Path], pyproject: Path, *,
    import_names: Mapping[str, str] | None = None, allowing: Iterable[str] = (),
) -> None:
    """A dependency nothing imports is fetched by every install and every CI run."""
    unimported = unimported_dependencies(
        root, packages, pyproject, import_names=import_names, allowing=allowing)
    assert not unimported, (
        "Declared and imported nowhere, so every install fetches it for nothing:\n  "
        + "\n  ".join(unimported))


_PLUGIN = re.compile(r"-p\s+([A-Za-z_][A-Za-z0-9_]*)")


def declared_siblings(pyproject: Path) -> set[str]:
    """The family checkouts a repo says it is installed beside.

    ``[project.dependencies]`` cannot hold them -- none of the three is
    published, so pip would go looking on PyPI -- and for years the record was a
    comment, which decayed: of the nine consumers, three named a sibling they no
    longer import and four named none at all while importing two.
    """
    with Path(pyproject).open("rb") as handle:
        table = tomllib.load(handle).get("tool", {}).get("haglio", {})
    return set(table.get("siblings", ()))


def sibling_imports(root: Path, packages: Iterable[Path], pyproject: Path) -> dict[str, list[str]]:
    """The siblings the *packages* need, with what needs them.

    A pytest plugin the config loads by name counts: ``-p
    app_support.sanitize.pytest_plugin`` is what arms the content guard, and a
    repo can need the package without a line of its own importing it.  A library
    importing itself does not: its own name is read off the project.
    """
    with Path(pyproject).open("rb") as handle:
        project = tomllib.load(handle)
    itself = _normalized(project.get("project", {}).get("name", ""))
    wanted = {name for name in FAMILY_SIBLINGS if _normalized(name) != itself}
    needed = {name: files for name, files in _imported_names(root, packages).items()
              if name in wanted}
    addopts = project.get("tool", {}).get("pytest", {}).get("ini_options", {}).get("addopts", "")
    for name in _PLUGIN.findall(addopts):
        if name in wanted:
            needed.setdefault(name, []).append(f"{Path(pyproject).name} (as a pytest plugin)")
    return {name: sorted(files) for name, files in sorted(needed.items())}


def _some_of(files: list[str], *, most: int = 3) -> str:
    shown = ", ".join(files[:most])
    return shown if len(files) <= most else f"{shown} and {len(files) - most} more"


def undeclared_siblings(root: Path, packages: Iterable[Path], pyproject: Path) -> list[str]:
    """Where the siblings a repo needs and the siblings it declares disagree, both ways."""
    needed = sibling_imports(root, packages, pyproject)
    declared = declared_siblings(pyproject)
    missing = [f"{name} is imported by {_some_of(files)} and declared nowhere"
               for name, files in needed.items() if name not in declared]
    return missing + [f"{name} is declared and imported nowhere"
                      for name in sorted(declared - set(needed))]


def assert_every_sibling_is_declared(root: Path, packages: Iterable[Path], pyproject: Path) -> None:
    """The siblings a repo is installed beside are the ones it says, exactly.

    Both directions: an undeclared one leaves the CI workflow as the only record
    of what a checkout needs, and a declared one nothing imports costs a clone
    and an install on every run while reading as a dependency to anyone deciding
    what may safely change.
    """
    wrong = undeclared_siblings(root, packages, pyproject)
    assert not wrong, "[tool.haglio] siblings is not what the tree needs:\n  " + "\n  ".join(wrong)


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

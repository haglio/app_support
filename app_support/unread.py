"""What is written and never read: the blind spots vulture has, scanned by the AST.

vulture counts an assignment as a use, so it never reports a module constant nothing
measures against, a constructor parameter stored on ``self`` and never read, a
dataclass field every build writes and nobody reads, or an ``argparse`` option the
parser declares and the app never consults. It is pointed at packages, so a helper
left behind in a test file accumulates unseen. Two repos wrote these scans for
themselves; they are published here so every repo asks the same questions::

    from app_support import unread

    PACKAGES = (ROOT / "the_package",)

    def test_no_module_level_constant_goes_unread():
        unread.assert_no_module_constant_goes_unread(ROOT, PACKAGES)

Every scan is a floor, not a proof: reads are matched by name across the whole
tree, plus every string literal (a ``getattr(obj, "name")`` counts), so a name that
collides with a live one elsewhere is not reported. That is the direction a gate
should err in.
"""
from __future__ import annotations

import ast
from pathlib import Path

_NOT_THE_REPOS = frozenset({".venv", "__pycache__", ".claude", ".git"})


def python_files(root) -> list[Path]:
    """Every ``.py`` under *root* that is the repo's own.

    Judged by the parts of the path relative to *root*, never the absolute
    path: a checkout under ``.claude/worktrees`` would otherwise skip itself.
    """
    root = Path(root)
    return sorted(
        path for path in root.rglob("*.py")
        if not _NOT_THE_REPOS & set(path.relative_to(root).parts)
    )


def _parse(path: Path) -> ast.Module | None:
    try:
        return ast.parse(path.read_text(encoding="utf-8"))
    except (SyntaxError, UnicodeDecodeError):
        return None


def _where(root, path: Path, lineno: int) -> str:
    return f"{path.relative_to(root).as_posix()}:{lineno}"


def _names_read_per_file(root) -> dict[Path, set[str]]:
    """Per file: every plain name and attribute read in it, its strings, and the
    first segment of everything it imports."""
    per_file: dict[Path, set[str]] = {}
    for path in python_files(root):
        tree = _parse(path)
        if tree is None:
            continue
        names: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
                names.add(node.id)
            elif isinstance(node, ast.Attribute) and isinstance(node.ctx, ast.Load):
                names.add(node.attr)
            elif isinstance(node, ast.Constant) and isinstance(node.value, str):
                names.add(node.value)
            elif isinstance(node, ast.alias):
                names.add(node.name.split(".")[0])
        per_file[path] = names
    return per_file


def _package_modules(packages) -> list[Path]:
    return sorted(path for package in packages for path in Path(package).rglob("*.py"))


def _not_allowed(found, allowing) -> list[str]:
    """*found* minus the reports whose name the repo allows -- a field read only
    by ``dataclasses.asdict``, a constant a sibling repo reads -- each named with
    its reason beside the call."""
    return [report for report in found if report.rsplit(": ", 1)[1] not in allowing]


def module_constants(root, packages) -> list[str]:
    """Module-level names assigned in *packages* and read nowhere in the tree.

    A name defined in one module and read only by another is safe; one read in
    no file but its own beyond the assignment itself is reported.
    """
    read = _names_read_per_file(root)
    found: list[str] = []
    for path in _package_modules(packages):
        tree = _parse(path)
        if tree is None:
            continue
        elsewhere: set[str] = set().union(
            *(names for other, names in read.items() if other != path))
        here = read.get(path, set())
        for node in tree.body:
            if isinstance(node, ast.Assign):
                targets = [t for t in node.targets if isinstance(t, ast.Name)]
            elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                targets = [node.target]
            else:
                continue
            found.extend(
                f"{_where(root, path, node.lineno)}: {target.id}"
                for target in targets
                if target.id not in here and target.id not in elsewhere)
    return found


def assert_no_module_constant_goes_unread(root, packages, *, allowing=()) -> None:
    """A constant nobody measures against is a number with no meaning left."""
    found = _not_allowed(module_constants(root, packages), allowing)
    assert not found, "Assigned and never read:\n" + "\n".join(found)


def _attribute_names_read_anywhere(root) -> set[str]:
    """Every ``x.<name>`` read in the tree, plus every string literal."""
    names: set[str] = set()
    for path in python_files(root):
        tree = _parse(path)
        if tree is None:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and isinstance(node.ctx, ast.Load):
                names.add(node.attr)
            elif isinstance(node, ast.Constant) and isinstance(node.value, str):
                names.add(node.value)
    return names


def _init_of(cls: ast.ClassDef) -> ast.FunctionDef | None:
    return next((f for f in cls.body
                 if isinstance(f, ast.FunctionDef) and f.name == "__init__"), None)


def _attributes_read_by_the_other_methods(cls: ast.ClassDef) -> set[str]:
    return {
        node.attr
        for method in cls.body
        if isinstance(method, ast.FunctionDef) and method.name != "__init__"
        for node in ast.walk(method)
        if isinstance(node, ast.Attribute) and isinstance(node.ctx, ast.Load)
    }


def stored_parameters(root, packages) -> list[str]:
    """``self.x = x`` in an ``__init__`` where nothing ever reads ``.x``.

    Unread by every other method of its own class, and unread under that name
    anywhere in the tree -- both, so an attribute a collaborator reads from
    outside does not count as dead.
    """
    read_anywhere = _attribute_names_read_anywhere(root)
    found: list[str] = []
    for path in _package_modules(packages):
        tree = _parse(path)
        if tree is None:
            continue
        for cls in (n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)):
            init = _init_of(cls)
            if init is None:
                continue
            params = {a.arg for a in init.args.args + init.args.kwonlyargs} - {"self"}
            read_in_class = _attributes_read_by_the_other_methods(cls)
            for stmt in ast.walk(init):
                if not (isinstance(stmt, ast.Assign) and len(stmt.targets) == 1):
                    continue
                target = stmt.targets[0]
                if (isinstance(target, ast.Attribute)
                        and isinstance(target.value, ast.Name)
                        and target.value.id == "self"
                        and isinstance(stmt.value, ast.Name)
                        and stmt.value.id in params
                        and target.attr not in read_in_class
                        and target.attr not in read_anywhere):
                    found.append(f"{_where(root, path, stmt.lineno)}: {cls.name}.{target.attr}")
    return found


def assert_no_constructor_parameter_is_stored_and_never_read(root, packages, *, allowing=()) -> None:
    """A signature that asks for something it does not use is a lie."""
    found = _not_allowed(stored_parameters(root, packages), allowing)
    assert not found, "Stored and never read:\n" + "\n".join(found)


def _is_collected_by_pytest(node: ast.FunctionDef) -> bool:
    """A test, a fixture or a hook is called by pytest, not by a name in the file."""
    if node.name.startswith(("test", "pytest_")):
        return True
    return any("fixture" in ast.unparse(d) or "hookimpl" in ast.unparse(d)
               for d in node.decorator_list)


def _names_imported_from_anywhere(root) -> set[str]:
    return {
        alias.name
        for path in python_files(root)
        if (tree := _parse(path)) is not None
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
        for alias in node.names
    }


def test_helpers(root, tests_dir) -> list[str]:
    """Functions in *tests_dir* that their own file never calls and no file imports.

    The gates that scan the packages do not scan the suite -- pointing vulture
    at tests reports every fake collaborator's methods -- so this is where a
    leftover helper accumulates unseen.
    """
    imported = _names_imported_from_anywhere(root)
    found: list[str] = []
    for path in sorted(Path(tests_dir).rglob("*.py")):
        tree = _parse(path)
        if tree is None:
            continue
        used = {
            node.id if isinstance(node, ast.Name) else node.attr
            for node in ast.walk(tree)
            if (isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load))
            or (isinstance(node, ast.Attribute) and isinstance(node.ctx, ast.Load))
        }
        found.extend(
            f"{_where(root, path, node.lineno)}: {node.name}"
            for node in tree.body
            if isinstance(node, ast.FunctionDef) and not _is_collected_by_pytest(node)
            and node.name not in used and node.name not in imported)
    return found


def assert_no_test_helper_is_written_and_never_called(root, tests_dir, *, allowing=()) -> None:
    found = _not_allowed(test_helpers(root, tests_dir), allowing)
    assert not found, "Written and never called:\n" + "\n".join(found)


def _attributes_read_or_named_in(packages) -> set[str]:
    """Every ``x.<name>`` in *packages*, plus the literal name of any
    ``getattr(x, "name", ...)``."""
    read: set[str] = set()
    for path in _package_modules(packages):
        tree = _parse(path)
        if tree is None:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute):
                read.add(node.attr)
            elif (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                    and node.func.id == "getattr" and len(node.args) >= 2
                    and isinstance(node.args[1], ast.Constant)):
                read.add(node.args[1].value)
    return read


def _argparse_dests(tree: ast.Module):
    """Every option an ``add_argument`` call in *tree* declares, as the attribute
    the parsed namespace will carry it under."""
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "add_argument"):
            continue
        explicit = [kw.value.value for kw in node.keywords
                    if kw.arg == "dest" and isinstance(kw.value, ast.Constant)]
        if explicit:
            yield explicit[0], node.lineno
            continue
        flags = [a.value for a in node.args if isinstance(a, ast.Constant)]
        long_flags = [f for f in flags if f.startswith("--")]
        spelling = next(iter(long_flags or flags), None)
        if spelling:
            yield spelling.lstrip("-").replace("-", "_"), node.lineno


def argparse_options(root, packages) -> list[str]:
    """Options a parser in *packages* declares that no attribute read in
    *packages* consults -- a launcher surface that does nothing."""
    declared: dict[str, str] = {}
    for path in _package_modules(packages):
        tree = _parse(path)
        if tree is None:
            continue
        for dest, lineno in _argparse_dests(tree):
            declared.setdefault(dest, _where(root, path, lineno))
    read = _attributes_read_or_named_in(packages)
    return [f"{where}: {dest}" for dest, where in sorted(declared.items(), key=lambda d: d[1])
            if dest not in read]


def assert_every_argparse_option_is_read(root, packages, *, allowing=()) -> None:
    found = _not_allowed(argparse_options(root, packages), allowing)
    assert not found, "command-line options nothing reads:\n" + "\n".join(found)


def _is_a_dataclass(cls: ast.ClassDef) -> bool:
    return any("dataclass" in ast.unparse(d) for d in cls.decorator_list)


def dataclass_fields(root, packages) -> list[str]:
    """Fields a dataclass in *packages* declares that nothing in *packages*
    reads -- state written on every build for nobody."""
    read = _attributes_read_or_named_in(packages)
    found: list[str] = []
    for path in _package_modules(packages):
        tree = _parse(path)
        if tree is None:
            continue
        for cls in (n for n in ast.walk(tree) if isinstance(n, ast.ClassDef) and _is_a_dataclass(n)):
            found.extend(
                f"{_where(root, path, statement.lineno)}: {cls.name}.{statement.target.id}"
                for statement in cls.body
                if isinstance(statement, ast.AnnAssign) and isinstance(statement.target, ast.Name)
                and statement.target.id not in read)
    return found


def assert_no_dataclass_field_goes_unread(root, packages, *, allowing=()) -> None:
    found = _not_allowed(dataclass_fields(root, packages), allowing)
    assert not found, "dataclass fields nothing reads:\n" + "\n".join(found)

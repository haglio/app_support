from __future__ import annotations

import ast
import os
from pathlib import Path

_NOT_THE_REPOS = frozenset({".venv", "__pycache__", ".claude", ".git", "state"})
_GETATTRS_NAME = 1


def python_files(root) -> list[Path]:
    found: list[Path] = []
    for folder, subfolders, files in os.walk(root):
        subfolders[:] = [name for name in subfolders if name not in _NOT_THE_REPOS]
        found.extend(Path(folder) / name for name in files if name.endswith(".py"))
    return sorted(found)


def _parse(path: Path) -> ast.Module | None:
    try:
        return ast.parse(path.read_text(encoding="utf-8"))
    except (SyntaxError, UnicodeDecodeError):
        return None


def _where(root, path: Path, lineno: int) -> str:
    return f"{path.relative_to(root).as_posix()}:{lineno}"


def _names_read_anywhere(root) -> set[str]:
    names: set[str] = set()
    for path in python_files(root):
        tree = _parse(path)
        if tree is None:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
                names.add(node.id)
            elif isinstance(node, ast.Attribute) and isinstance(node.ctx, ast.Load):
                names.add(node.attr)
            elif isinstance(node, ast.Constant) and isinstance(node.value, str):
                names.add(node.value)
            elif isinstance(node, ast.alias):
                names.add(node.name.split(".")[0])
    return names


def _package_modules(packages) -> list[Path]:
    return sorted(path for package in packages for path in Path(package).rglob("*.py"))


def not_allowed(found: dict[str, str], allowing) -> list[str]:
    return ([report for report, name in found.items() if name not in allowing]
            + [f"allowed, and no longer reported -- take it off the list: {name}"
               for name in allowing if name not in found.values()])


def _not_allowed(found, allowing) -> list[str]:
    return not_allowed({report: report.rsplit(": ", 1)[1] for report in found}, allowing)


_NAMES_PYTEST_READS_OFF_A_MODULE = frozenset({"pytestmark", "pytest_plugins"})


def _read_by_the_language_or_its_tools(name: str) -> bool:
    return (name.startswith("__") and name.endswith("__")) or name in _NAMES_PYTEST_READS_OFF_A_MODULE


def module_constants(root, packages) -> list[str]:
    read_anywhere = _names_read_anywhere(root)
    found: list[str] = []
    for path in _package_modules(packages):
        tree = _parse(path)
        if tree is None:
            continue
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
                if not _read_by_the_language_or_its_tools(target.id)
                and target.id not in read_anywhere)
    return found


def assert_no_module_constant_goes_unread(root, packages, *, allowing=()) -> None:
    found = _not_allowed(module_constants(root, packages), allowing)
    assert not found, "Assigned and never read:\n" + "\n".join(found)


def _attribute_names_read_anywhere(root) -> set[str]:
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
    found = _not_allowed(stored_parameters(root, packages), allowing)
    assert not found, "Stored and never read:\n" + "\n".join(found)


def _is_collected_by_pytest(node: ast.FunctionDef) -> bool:
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
    read: set[str] = set()
    for path in _package_modules(packages):
        tree = _parse(path)
        if tree is None:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute):
                read.add(node.attr)
            elif (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                    and node.func.id == "getattr" and len(node.args) > _GETATTRS_NAME
                    and isinstance(node.args[_GETATTRS_NAME], ast.Constant)):
                read.add(node.args[_GETATTRS_NAME].value)
    return read


def _argparse_dests(tree: ast.Module):
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

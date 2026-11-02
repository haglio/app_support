"""What the modules of a repository take from one another, read off their source.

A name taken through a package that only re-exports it counts against the module
that defines it, so a gathering ``__init__.py`` hides nothing and owes nothing.
"""
from __future__ import annotations

import ast
from collections.abc import Iterable, Iterator, Mapping
from pathlib import PurePosixPath

from app_support.coupling.statements import own_statements
from app_support.python_source import top_of

_INIT = "__init__"
_MUTABLE_LITERALS = (ast.List, ast.Dict, ast.Set, ast.ListComp, ast.DictComp, ast.SetComp)
_MUTABLE_MAKERS = frozenset({"list", "dict", "set", "defaultdict", "deque", "Counter", "OrderedDict"})
_IMPORTERS = frozenset({"__import__", "import_module"})

APP_PACKAGES = frozenset({
    "backfill", "evolver", "fun_time", "fun_time_vr", "genaumacher", "line", "main_funestra", "origenerator",
    "osr2_broker", "promptcrafter", "review_weird", "satellite", "scripture",
})


def _module_name(path: str) -> str:
    parts = PurePosixPath(path).with_suffix("").parts
    return ".".join(parts[:-1] if parts[-1] == _INIT else parts)


def _only_gathers(tree: ast.Module) -> bool:
    return all(isinstance(statement, (ast.Import, ast.ImportFrom))
               or (isinstance(statement, ast.Assign) and any(
                   isinstance(target, ast.Name) and target.id == "__all__" for target in statement.targets))
               or (isinstance(statement, ast.Expr) and isinstance(statement.value, ast.Constant))
               for statement in tree.body)


def _is_mutable_container(value: ast.expr | None) -> bool:
    if isinstance(value, ast.Call):
        func = value.func
        return (func.id if isinstance(func, ast.Name) else getattr(func, "attr", "")) in _MUTABLE_MAKERS
    return isinstance(value, _MUTABLE_LITERALS)


def _mutables_bound_in(tree: ast.Module) -> set[str]:
    names: set[str] = set()
    for statement in own_statements(tree):
        if isinstance(statement, ast.Assign) and _is_mutable_container(statement.value):
            names |= {target.id for target in statement.targets if isinstance(target, ast.Name)}
        elif (isinstance(statement, ast.AnnAssign) and isinstance(statement.target, ast.Name)
              and _is_mutable_container(statement.value)):
            names.add(statement.target.id)
    return names


def _dotted(node: ast.expr) -> str | None:
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    return ".".join((node.id, *reversed(parts))) if isinstance(node, ast.Name) else None


def _absolute(path: str, node: ast.ImportFrom) -> str:
    if not node.level:
        return node.module or ""
    package = PurePosixPath(path).parent.parts
    kept = package[:len(package) - node.level + 1]
    return ".".join((*kept, *([node.module] if node.module else [])))


class ModuleTree:
    def __init__(self, sources: Mapping[str, str]) -> None:
        self._trees = {path: ast.parse(source) for path, source in sources.items()}
        self._path_of = {_module_name(path): path for path in sources}
        self._gathers = {path for path, tree in self._trees.items()
                         if PurePosixPath(path).stem == _INIT and _only_gathers(tree)}

    def _defined_by(self, module: str, name: str) -> str:
        where = self._path_of[module]
        if where in self._gathers:
            for node in self._trees[where].body:
                if isinstance(node, ast.ImportFrom):
                    source = _absolute(where, node)
                    for alias in node.names:
                        if (alias.asname or alias.name) == name and source in self._path_of and source != module:
                            return self._defined_by(source, alias.name)
        return module

    def _module_taken(self, module: str, name: str) -> str | None:
        if f"{module}.{name}" in self._path_of:
            return f"{module}.{name}"
        return self._defined_by(module, name) if module in self._path_of else None

    def _longest_module_within(self, dotted: str) -> str | None:
        parts = dotted.split(".")
        candidates = (".".join(parts[:length]) for length in range(len(parts), 0, -1))
        return next((candidate for candidate in candidates if candidate in self._path_of), None)

    def _modules_imported_by(self, path: str) -> Iterator[str | None]:
        for node in ast.walk(self._trees[path]):
            if isinstance(node, ast.Import):
                yield from (self._longest_module_within(alias.name) for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                module = _absolute(path, node)
                yield from (self._module_taken(module, alias.name) for alias in node.names)

    def fan_out(self) -> dict[str, int]:
        return {path: 0 if path in self._gathers
                else len(set(self._modules_imported_by(path)) - {_module_name(path), None})
                for path in self._trees}

    def _modules_bound_to_names_in(self, path: str) -> dict[str, str]:
        bound = {}
        for node in ast.walk(self._trees[path]):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    bound[alias.asname or top_of(alias.name)] = alias.name if alias.asname else top_of(alias.name)
            elif isinstance(node, ast.ImportFrom):
                module = _absolute(path, node)
                for alias in node.names:
                    if f"{module}.{alias.name}" in self._path_of:
                        bound[alias.asname or alias.name] = f"{module}.{alias.name}"
        return bound

    def _names_taken_by(self, path: str) -> Iterator[tuple[str, str]]:
        tree = self._trees[path]
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                module = _absolute(path, node)
                for alias in node.names:
                    if module in self._path_of and f"{module}.{alias.name}" not in self._path_of:
                        yield self._defined_by(module, alias.name), alias.name
        bound = self._modules_bound_to_names_in(path)
        for node in ast.walk(tree):
            dotted = _dotted(node.value) if isinstance(node, ast.Attribute) else None
            if dotted and top_of(dotted) in bound:
                module = bound[top_of(dotted)] + dotted[len(top_of(dotted)):]
                if module in self._path_of:
                    yield self._defined_by(module, node.attr), node.attr

    def mutables_imported(self) -> dict[str, int]:
        mutables = {module: _mutables_bound_in(self._trees[where]) for module, where in self._path_of.items()}
        taken = {(module, name)
                 for path in self._trees
                 for module, name in self._names_taken_by(path)
                 if module != _module_name(path) and name in mutables[module]}
        counted: dict[str, int] = {}
        for module, _name in taken:
            counted[self._path_of[module]] = counted.get(self._path_of[module], 0) + 1
        return counted


def _imported_tops(tree: ast.Module) -> Iterator[str]:
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            yield from (top_of(alias.name) for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and not node.level and node.module:
            yield top_of(node.module)
        elif isinstance(node, ast.Call) and node.args and isinstance(node.args[0], ast.Constant):
            called = node.func.id if isinstance(node.func, ast.Name) else getattr(node.func, "attr", "")
            if called in _IMPORTERS and isinstance(node.args[0].value, str):
                yield top_of(node.args[0].value)


def another_apps_imports(sources: Mapping[str, str], *, own: Iterable[str]) -> dict[str, int]:
    others = APP_PACKAGES - set(own)
    counted = {path: sum(top in others for top in _imported_tops(ast.parse(source)))
               for path, source in sources.items()}
    return {path: count for path, count in counted.items() if count}

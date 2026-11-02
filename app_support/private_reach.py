"""Reads of another object's private name through any handle, and imports of a private name charged to the module that defines it."""
from __future__ import annotations

import ast
from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import NamedTuple

_PUBLISHED_BY_NAMEDTUPLE = frozenset({"_replace", "_asdict", "_fields", "_make", "_field_defaults"})
_PUBLISHED_BY_MODULE = frozenset({("os", "_exit"), ("sys", "_getframe"), ("sys", "_MEIPASS")})
_COMPARISONS = frozenset({"__eq__", "__ne__", "__lt__", "__le__", "__gt__", "__ge__"})
_READS_BY_NAME = frozenset({"getattr", "setattr", "hasattr", "delattr"})
_SCOPES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)


class Reach(NamedTuple):
    line: int
    written: str


def _is_private(name: str) -> bool:
    return name.startswith("_") and not name.endswith("_")


def reaches_in(source: str) -> list[Reach]:
    walker = _Reaches()
    walker.visit(ast.parse(source))
    return walker.found


def _nodes_of_this_scope(function: ast.AST) -> Iterator[ast.AST]:
    waiting = list(ast.iter_child_nodes(function))
    while waiting:
        node = waiting.pop()
        yield node
        if not isinstance(node, _SCOPES):
            waiting.extend(ast.iter_child_nodes(node))


def _bound_by(target: ast.expr, value: ast.expr | None) -> Iterator[tuple[str, ast.expr | None]]:
    if isinstance(target, ast.Name):
        yield target.id, value
    elif isinstance(target, ast.Starred):
        yield from _bound_by(target.value, None)
    elif isinstance(target, (ast.Tuple, ast.List)):
        for element in target.elts:
            yield from _bound_by(element, None)


def _bindings_in(function: ast.AST) -> Iterator[tuple[str, ast.expr | None]]:
    for node in _nodes_of_this_scope(function):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                yield from _bound_by(target, node.value)
        elif isinstance(node, (ast.AnnAssign, ast.NamedExpr)) and node.value is not None:
            yield from _bound_by(node.target, node.value)
        elif isinstance(node, (ast.AugAssign, ast.For, ast.AsyncFor, ast.comprehension)):
            yield from _bound_by(node.target, None)
        elif isinstance(node, ast.withitem) and node.optional_vars is not None:
            yield from _bound_by(node.optional_vars, None)


def _parameters(function: ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda) -> list[ast.arg]:
    arguments = function.args
    named = [*arguments.posonlyargs, *arguments.args, *arguments.kwonlyargs]
    return named + [extra for extra in (arguments.vararg, arguments.kwarg) if extra is not None]


def _is_static(function: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    return any(isinstance(decorator, ast.Name) and decorator.id == "staticmethod"
               for decorator in function.decorator_list)


def _class_annotated(parameter: ast.arg) -> str | None:
    annotation = parameter.annotation
    if isinstance(annotation, ast.Name):
        return annotation.id
    if isinstance(annotation, ast.Constant) and isinstance(annotation.value, str):
        return annotation.value
    return None


class _Reaches(ast.NodeVisitor):
    def __init__(self) -> None:
        self.found: list[Reach] = []
        self._classes: list[str] = []
        self._own: frozenset[str] = frozenset()
        self._directly_in_a_class = False

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self._classes.append(node.name)
        was_directly, self._directly_in_a_class = self._directly_in_a_class, True
        self.generic_visit(node)
        self._directly_in_a_class = was_directly
        self._classes.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        was_own, was_directly = self._own, self._directly_in_a_class
        self._own = self._own_names_in(node)
        self._directly_in_a_class = False
        self.generic_visit(node)
        self._own, self._directly_in_a_class = was_own, was_directly

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_Lambda(self, node: ast.Lambda) -> None:
        was_own = self._own
        self._own = self._own - {parameter.arg for parameter in _parameters(node)}
        self.generic_visit(node)
        self._own = was_own

    def _own_names_in(self, function: ast.FunctionDef | ast.AsyncFunctionDef) -> frozenset[str]:
        parameters = _parameters(function)
        own = set(self._own) - {parameter.arg for parameter in parameters}
        if self._directly_in_a_class and parameters and not _is_static(function):
            own.add(parameters[0].arg)
        if self._directly_in_a_class and function.name in _COMPARISONS:
            own.update(parameter.arg for parameter in parameters)
        own.update(parameter.arg for parameter in parameters if _class_annotated(parameter) in self._classes)
        return self._settled(own, function)

    def _settled(self, own: set[str], function: ast.AST) -> frozenset[str]:
        bindings: dict[str, list[ast.expr | None]] = {}
        for name, value in _bindings_in(function):
            bindings.setdefault(name, []).append(value)
        own -= set(bindings)
        while True:
            more = {name for name, values in bindings.items()
                    if name not in own and all(self._is_own(value, own) for value in values)}
            if not more:
                return frozenset(own)
            own |= more

    def _is_own(self, value: ast.expr | None, own: set[str] | frozenset[str]) -> bool:
        if isinstance(value, ast.Name):
            return value.id in own or value.id in self._classes
        if isinstance(value, ast.Attribute):
            return value.attr == "__class__" and self._is_own(value.value, own)
        if not isinstance(value, ast.Call):
            return False
        if isinstance(value.func, ast.Name) and value.func.id == "super":
            return True
        if isinstance(value.func, ast.Name) and value.func.id == "type" and len(value.args) == 1:
            return self._is_own(value.args[0], own)
        return self._is_own(value.func, own)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        self._judge(node.value, node.attr, node)
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        match node:
            case ast.Call(func=ast.Name(id=reader), args=[receiver, ast.Constant(value=str(name)), *_]):
                if reader in _READS_BY_NAME:
                    self._judge(receiver, name, node)
        self.generic_visit(node)

    def _judge(self, receiver: ast.expr, name: str, node: ast.expr) -> None:
        if not _is_private(name) or name in _PUBLISHED_BY_NAMEDTUPLE:
            return
        if isinstance(receiver, ast.Name) and (receiver.id, name) in _PUBLISHED_BY_MODULE:
            return
        if not self._is_own(receiver, self._own):
            self.found.append(Reach(node.lineno, ast.unparse(node)))


def _absolute(node: ast.ImportFrom, module: str, is_package: bool) -> str:
    if not node.level:
        return node.module or ""
    parts = module.split(".")
    climbed = parts[:len(parts) - node.level + (1 if is_package else 0)]
    return ".".join([*climbed, *([node.module] if node.module else [])])


class _Modules:
    def __init__(self, files: Iterable[Path], root: Path) -> None:
        self.parsed = {path: ast.parse(path.read_text(encoding="utf-8")) for path in files}
        self.names = {path: self._name_of(path, root) for path in self.parsed}
        self._handed_on = {self.names[path]: dict(self._names_handed_on(path, tree))
                           for path, tree in self.parsed.items()}

    @staticmethod
    def _name_of(path: Path, root: Path) -> str:
        parts = path.relative_to(root).with_suffix("").parts
        return ".".join(parts[:-1] if parts[-1] == "__init__" else parts)

    def _names_handed_on(self, path: Path, tree: ast.Module) -> Iterator[tuple[str, tuple[str, str]]]:
        for node in tree.body:
            if isinstance(node, ast.ImportFrom):
                source = _absolute(node, self.names[path], path.stem == "__init__")
                for alias in node.names:
                    yield alias.asname or alias.name, (source, alias.name)

    def _definer(self, module: str, name: str) -> tuple[str, str]:
        seen = set()
        while (module, name) not in seen and name in self._handed_on.get(module, {}):
            seen.add((module, name))
            module, name = self._handed_on[module][name]
        return module, name

    def is_a_module(self, name: str) -> bool:
        return name in self._handed_on

    def charge_for(self, source: str, name: str) -> str | None:
        if _is_private(name):
            return f"{name} of {source}"
        definer, defined = self._definer(source, name)
        return f"{defined} of {definer}, as {name} of {source}" if _is_private(defined) else None


def _holder_of_a_private_module(module: str) -> str | None:
    parts = module.split(".")
    for depth, part in enumerate(parts):
        if _is_private(part):
            return ".".join(parts[:depth])
    return None


def _is_inside(package: str, module: str) -> bool:
    return module == package or module.startswith(f"{package}.")


def _reaches_a_private_module(module: str, importer: str) -> bool:
    holder = _holder_of_a_private_module(module)
    return holder is not None and not _is_inside(holder, importer)


def _charges_in(modules: _Modules, path: Path, tree: ast.Module) -> Iterator[tuple[int, str]]:
    importer = modules.names[path]
    held: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if _reaches_a_private_module(alias.name, importer):
                    yield node.lineno, alias.name
                held[alias.asname or alias.name] = alias.name
        elif isinstance(node, ast.ImportFrom):
            source = _absolute(node, importer, path.stem == "__init__")
            if _reaches_a_private_module(source, importer):
                yield node.lineno, source
                continue
            for alias in node.names:
                held[alias.asname or alias.name] = f"{source}.{alias.name}"
                its_own_private_module = _is_inside(source, importer) and modules.is_a_module(f"{source}.{alias.name}")
                charge = None if its_own_private_module else modules.charge_for(source, alias.name)
                if charge:
                    yield node.lineno, charge
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and not _is_private(node.attr):
            module = held.get(ast.unparse(node.value))
            charge = modules.charge_for(module, node.attr) if module and modules.is_a_module(module) else None
            if charge:
                yield node.lineno, charge


def private_imports(files: Iterable[Path], root: Path) -> dict[str, list[str]]:
    modules = _Modules(files, root)
    charged: dict[str, list[str]] = {}
    for path, tree in modules.parsed.items():
        relative = path.relative_to(root).as_posix()
        charges = sorted(_charges_in(modules, path, tree))
        if charges:
            charged[relative] = [f"{relative}:{line}: {charge}" for line, charge in charges]
    return charged

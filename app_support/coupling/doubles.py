"""The test doubles a test file reaches for, read off its source.

Each is followed through its aliases rather than matched as a word, so
``from unittest.mock import patch as swap`` is still a patch and a class of the
repo's own called ``Mock`` is not one.
"""
from __future__ import annotations

import ast
from collections.abc import Iterable, Iterator
from dataclasses import dataclass

from app_support.dependencies import family_packages
from app_support.python_source import top_of

_MOCK = "unittest.mock."
_MOCKS = frozenset(_MOCK + name for name in (
    "Mock", "MagicMock", "AsyncMock", "NonCallableMock", "NonCallableMagicMock", "PropertyMock", "create_autospec"))
_PATCH = _MOCK + "patch"
_PATCHES = frozenset({_PATCH, f"{_PATCH}.object", f"{_PATCH}.dict", f"{_PATCH}.multiple"})
_BAG = "types.SimpleNamespace"
_MONKEYPATCH = "monkeypatch"
_MONKEYPATCH_MAKERS = frozenset({"pytest.MonkeyPatch()", "pytest.MonkeyPatch.context()",
                                 "_pytest.monkeypatch.MonkeyPatch()", "_pytest.monkeypatch.MonkeyPatch.context()"})
_MONKEYPATCH_TYPES = frozenset({"pytest.MonkeyPatch", "_pytest.monkeypatch.MonkeyPatch"})
_MONKEYPATCH_SET = f"{_MONKEYPATCH}.setattr"
_MONKEYPATCH_REPLACING = frozenset({_MONKEYPATCH_SET, f"{_MONKEYPATCH}.delattr", f"{_MONKEYPATCH}.setitem",
                                    f"{_MONKEYPATCH}.delitem"})
_LIBRARY_TEST_SURFACE = "testing"
_LOCAL_DEFINITIONS = (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)


@dataclass(frozen=True)
class Doubles:
    mocks: int = 0
    patches: int = 0
    monkeypatches: int = 0
    simple_namespaces: int = 0
    library_patches: int = 0


class _Names:
    """What each name in a file stands for: a dotted path, or text it holds."""

    def __init__(self, tree: ast.Module) -> None:
        self.dotted: dict[str, str] = {}
        self.text: dict[str, str] = {}
        self.locally_defined = {node.name for node in ast.walk(tree) if isinstance(node, _LOCAL_DEFINITIONS)}
        for _ in range(2):
            for node in ast.walk(tree):
                self._learn(node)

    def _learn(self, node: ast.AST) -> None:
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.asname:
                    self.dotted[alias.asname] = alias.name
        elif isinstance(node, ast.ImportFrom) and not node.level and node.module:
            for alias in node.names:
                self.dotted[alias.asname or alias.name] = f"{node.module}.{alias.name}"
        elif isinstance(node, ast.arg) and node.annotation is not None:
            if self.resolve(node.annotation) in _MONKEYPATCH_TYPES:
                self.dotted[node.arg] = _MONKEYPATCH
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                self._bind(target, node.value)
        elif isinstance(node, ast.withitem) and node.optional_vars is not None:
            self._bind(node.optional_vars, node.context_expr)

    def _bind(self, target: ast.expr, value: ast.expr) -> None:
        key = self._spelled(target)
        if key is None:
            return
        if isinstance(value, ast.Constant) and isinstance(value.value, str):
            self.text[key] = value.value
        resolved = self.resolve(value)
        if resolved in _MONKEYPATCH_MAKERS:
            self.dotted[key] = _MONKEYPATCH
        elif resolved is not None and resolved != key:
            self.dotted[key] = resolved

    def _spelled(self, node: ast.expr) -> str | None:
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.Attribute):
            inner = self._spelled(node.value)
            return f"{inner}.{node.attr}" if inner else None
        return None

    def resolve(self, node: ast.expr) -> str | None:
        if isinstance(node, ast.Name):
            return None if node.id in self.locally_defined else self.dotted.get(node.id, node.id)
        if isinstance(node, ast.Attribute):
            spelled = self._spelled(node)
            if spelled in self.dotted:
                return self.dotted[spelled]
            inner = self.resolve(node.value)
            return f"{inner}.{node.attr}" if inner else None
        if isinstance(node, ast.Call):
            inner = self.resolve(node.func)
            return f"{inner}()" if inner else None
        return None

    def target_of(self, node: ast.expr) -> str | None:
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return node.value
        if isinstance(node, ast.JoinedStr) and node.values and isinstance(node.values[0], ast.Constant):
            return str(node.values[0].value)
        if isinstance(node, ast.Name) and node.id in self.text:
            return self.text[node.id]
        return self.resolve(node)


def _references(tree: ast.Module) -> Iterator[ast.expr]:
    """Every name read as a value: an annotation says what a thing is, and doubles nothing."""
    waiting: list[ast.AST] = [tree]
    while waiting:
        node = waiting.pop()
        if isinstance(node, (ast.Name, ast.Attribute)) and isinstance(node.ctx, ast.Load):
            yield node
        waiting += [child for field, child in _children(node) if field not in {"annotation", "returns"}]


def _children(node: ast.AST) -> Iterator[tuple[str, ast.AST]]:
    for field, value in ast.iter_fields(node):
        for child in value if isinstance(value, list) else [value]:
            if isinstance(child, ast.AST):
                yield field, child


def _is_inside_a_library(target: str | None, own: Iterable[str]) -> bool:
    if target is None or top_of(target) not in set(family_packages()) - set(own):
        return False
    return target.split(".")[1:2] != [_LIBRARY_TEST_SURFACE]


def count_doubles(source: str, *, own: Iterable[str]) -> Doubles:
    tree = ast.parse(source)
    names = _Names(tree)
    mocks = sum(names.resolve(node) in _MOCKS for node in _references(tree))
    called = [(names.resolve(node.func), node) for node in ast.walk(tree) if isinstance(node, ast.Call)]
    replacing = [node for resolved, node in called if resolved in _PATCHES or resolved in _MONKEYPATCH_REPLACING]
    return Doubles(
        mocks=mocks,
        patches=sum(resolved in _PATCHES for resolved, _ in called),
        monkeypatches=sum(resolved == _MONKEYPATCH_SET for resolved, _ in called),
        simple_namespaces=sum(resolved == _BAG for resolved, _ in called),
        library_patches=sum(bool(node.args) and _is_inside_a_library(names.target_of(node.args[0]), own)
                            for node in replacing),
    )

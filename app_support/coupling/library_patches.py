from __future__ import annotations

import ast
from collections.abc import Iterable

from app_support.dependencies import family_packages
from app_support.python_source import top_of

_PATCH = "unittest.mock.patch"
_PATCHES = frozenset({_PATCH, f"{_PATCH}.object", f"{_PATCH}.dict", f"{_PATCH}.multiple"})
_MONKEYPATCH = "monkeypatch"
_MONKEYPATCH_MAKERS = frozenset({"pytest.MonkeyPatch()", "pytest.MonkeyPatch.context()",
                                 "_pytest.monkeypatch.MonkeyPatch()", "_pytest.monkeypatch.MonkeyPatch.context()"})
_MONKEYPATCH_TYPES = frozenset({"pytest.MonkeyPatch", "_pytest.monkeypatch.MonkeyPatch"})
_MONKEYPATCH_REPLACING = frozenset({f"{_MONKEYPATCH}.setattr", f"{_MONKEYPATCH}.delattr", f"{_MONKEYPATCH}.setitem",
                                    f"{_MONKEYPATCH}.delitem"})
_LIBRARY_TEST_SURFACE = "testing"
_LOCAL_DEFINITIONS = (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)


class _Names:
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


def _is_inside_a_library(target: str | None, own: Iterable[str]) -> bool:
    if target is None or top_of(target) not in set(family_packages()) - set(own):
        return False
    return target.split(".")[1:2] != [_LIBRARY_TEST_SURFACE]


def library_patches_in(source: str, *, own: Iterable[str]) -> int:
    tree = ast.parse(source)
    names = _Names(tree)
    replacing = [node for node in ast.walk(tree) if isinstance(node, ast.Call)
                 and names.resolve(node.func) in _PATCHES | _MONKEYPATCH_REPLACING]
    return sum(bool(node.args) and _is_inside_a_library(names.target_of(node.args[0]), own) for node in replacing)

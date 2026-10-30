"""What a module of Python defines, and what it uses of a package, read off its source.

Standard library only.
"""
from __future__ import annotations

import ast
import re
from collections.abc import Iterable, Mapping

_SCOPES = (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)


def without_docstrings(tree: ast.Module) -> ast.Module:
    """Every scope's, not only the file's: nothing runs a docstring."""
    for node in ast.walk(tree):
        if isinstance(node, _SCOPES):
            node.body = _past_the_docstring(node.body)
    return tree


def _past_the_docstring(body: list[ast.stmt]) -> list[ast.stmt]:
    first = body[0] if body else None
    if (isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant)
            and isinstance(first.value.value, str)):
        return body[1:]
    return body


class _ModuleBindings(ast.NodeVisitor):
    def __init__(self) -> None:
        self.names: set[str] = set()

    def visit_FunctionDef(self, node: ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef) -> None:
        self.names.add(node.name)

    visit_AsyncFunctionDef = visit_ClassDef = visit_FunctionDef

    def visit_Lambda(self, node: ast.Lambda) -> None:
        pass

    def visit_Import(self, node: ast.Import | ast.ImportFrom) -> None:
        self.names.update(top_of(alias.asname or alias.name) for alias in node.names if alias.name != "*")

    visit_ImportFrom = visit_Import

    def visit_Name(self, node: ast.Name) -> None:
        if isinstance(node.ctx, ast.Store):
            self.names.add(node.id)

    def visit_ExceptHandler(self, node: ast.ExceptHandler) -> None:
        if node.name:
            self.names.add(node.name)
        self.generic_visit(node)


def names_defined(source: str) -> set[str]:
    bindings = _ModuleBindings()
    bindings.visit(ast.parse(source))
    return bindings.names


def top_of(dotted: str) -> str:
    return dotted.partition(".")[0]


def _in(dotted: str, packages: Iterable[str]) -> bool:
    return top_of(dotted) in packages


class _Uses(ast.NodeVisitor):
    def __init__(self, bound: Mapping[str, str]) -> None:
        self.bound = bound
        self.found: set[str] = set()

    def visit_Attribute(self, node: ast.Attribute) -> None:
        chain = []
        inner: ast.expr = node
        while isinstance(inner, ast.Attribute):
            chain.append(inner.attr)
            inner = inner.value
        if isinstance(inner, ast.Name) and inner.id in self.bound:
            self.found.add(".".join([self.bound[inner.id], *reversed(chain)]))
        else:
            self.visit(inner)


def _imports(tree: ast.AST, packages: set[str]) -> tuple[set[str], dict[str, str]]:
    found, bound = set(), {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if _in(alias.name, packages):
                    found.add(alias.name)
                    top = top_of(alias.name)
                    bound[alias.asname or top] = alias.name if alias.asname else top
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module and _in(node.module, packages):
            for alias in node.names:
                dotted = f"{node.module}.{alias.name}"
                found.add(dotted)
                bound[alias.asname or alias.name] = dotted
    return found, bound


def spelled_out(text: str, packages: Iterable[str]) -> set[str]:
    either = "|".join(re.escape(package) for package in sorted(packages))
    pattern = rf"(?<![\w.])(?:{either})(?:[.:][A-Za-z_][A-Za-z0-9_]*)+"
    return {found.replace(":", ".") for found in re.findall(pattern, text)}


def references(source: str, packages: Iterable[str]) -> set[str]:
    packages = set(packages)
    tree = without_docstrings(ast.parse(source))
    found, bound = _imports(tree, packages)
    uses = _Uses(bound)
    uses.visit(tree)
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            found |= spelled_out(node.value, packages)
    return found | uses.found

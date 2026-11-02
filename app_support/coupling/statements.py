"""The statements that belong to a body: inside its blocks, and never inside a nested definition."""
from __future__ import annotations

import ast
from collections.abc import Iterator

_DEFINITIONS = (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)


def own_statements(owner: ast.Module | ast.ClassDef) -> Iterator[ast.stmt]:
    waiting: list[ast.AST] = list(owner.body)
    while waiting:
        node = waiting.pop()
        if isinstance(node, ast.stmt):
            yield node
        if not isinstance(node, _DEFINITIONS):
            waiting += [child for child in ast.iter_child_nodes(node)
                        if isinstance(child, (ast.stmt, ast.ExceptHandler))]

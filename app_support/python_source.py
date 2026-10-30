"""What a module of Python says, read off its source.

Standard library only.
"""
from __future__ import annotations

import ast

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

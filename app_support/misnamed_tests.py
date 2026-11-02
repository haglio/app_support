from __future__ import annotations

import ast
from pathlib import Path

from app_support.unread import python_files


def _holds_tests(source: str) -> bool:
    for node in ast.parse(source).body:
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and node.name.startswith("test_"):
            return True
        if isinstance(node, ast.ClassDef) and node.name.startswith("Test") and any(
                isinstance(method, ast.FunctionDef | ast.AsyncFunctionDef) and method.name.startswith("test_")
                for method in node.body):
            return True
    return False


def files_holding_tests_pytest_never_runs(tests: Path) -> list[Path]:
    return [path for path in python_files(tests)
            if not path.name.startswith("test_") and _holds_tests(path.read_text(encoding="utf-8"))]


def assert_every_file_holding_tests_is_named_test(tests: Path) -> None:
    __tracebackhide__ = True
    misnamed = files_holding_tests_pytest_never_runs(tests)
    assert not misnamed, f"pytest runs none of these, each not named test_*.py: {[str(path) for path in misnamed]}"

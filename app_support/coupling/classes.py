"""What a class is made of and how far it reaches, read off its source.

A chain is ``self.a.b``: a method reaching through what it holds into what that
holds. Handing the first hop to a local first is still the chain, so a local is
followed through every way of binding one.
"""
from __future__ import annotations

import ast
from dataclasses import dataclass, field

from app_support.coupling.statements import own_statements

_DEFINITION = (ast.FunctionDef, ast.AsyncFunctionDef)
_SHORTEST_CHAIN = 2


@dataclass
class ClassSurface:
    methods: int = 0
    attributes: int = 0
    chains: int = 0
    longest_chain: int = 0


def _binding(node: ast.AST) -> tuple[ast.expr | None, list[ast.expr]]:
    if isinstance(node, ast.Assign):
        return node.value, node.targets
    if isinstance(node, (ast.AnnAssign, ast.NamedExpr)):
        return node.value, [node.target]
    if isinstance(node, ast.withitem):
        return node.context_expr, [node.optional_vars] if node.optional_vars else []
    return None, []


@dataclass
class _Reach(ast.NodeVisitor):
    surface: ClassSurface
    bound: set[str]
    hops_of: dict[str, int] = field(default_factory=dict)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        hops = self._hops(node)
        if hops == 1 and isinstance(node.ctx, ast.Store):
            self.bound.add(node.attr)
        if hops is None:
            self.generic_visit(node)
        elif hops >= _SHORTEST_CHAIN:
            self.surface.chains += 1
            self.surface.longest_chain = max(self.surface.longest_chain, hops)

    def _hops(self, node: ast.expr) -> int | None:
        count = 0
        while isinstance(node, ast.Attribute):
            count += 1
            node = node.value
        if isinstance(node, ast.Name) and node.id in self.hops_of:
            return self.hops_of[node.id] + count
        return None

    def _bind(self, target: ast.expr, value: ast.expr) -> None:
        if isinstance(target, ast.Tuple) and isinstance(value, ast.Tuple) and len(target.elts) == len(value.elts):
            for one_target, one_value in zip(target.elts, value.elts, strict=True):
                self._bind(one_target, one_value)
        elif isinstance(target, ast.Name):
            hops = self._hops(value)
            if hops is None:
                self.hops_of.pop(target.id, None)
            else:
                self.hops_of[target.id] = hops

    def generic_visit(self, node: ast.AST) -> None:
        value, targets = _binding(node)
        if value is None:
            super().generic_visit(node)
            return
        self.visit(value)
        for target in targets:
            self._bind(target, value)
            if not isinstance(target, ast.Name):
                self.visit(target)


def _is_static(method: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    return any(isinstance(mark, ast.Name) and mark.id == "staticmethod" for mark in method.decorator_list)


def _names_bound_in_the_body(statements: list[ast.stmt]) -> set[str]:
    names = set()
    for statement in statements:
        if isinstance(statement, ast.Assign):
            names |= {target.id for target in statement.targets if isinstance(target, ast.Name)}
        elif isinstance(statement, ast.AnnAssign) and isinstance(statement.target, ast.Name):
            names.add(statement.target.id)
    return {name for name in names if not (name.startswith("__") and name.endswith("__"))}


def _measure_class(owner: ast.ClassDef) -> ClassSurface:
    statements = list(own_statements(owner))
    methods = [statement for statement in statements if isinstance(statement, _DEFINITION)]
    surface = ClassSurface(methods=len(methods))
    bound = _names_bound_in_the_body(statements)
    for method in methods:
        receiver = {method.args.args[0].arg: 0} if method.args.args and not _is_static(method) else {}
        reach = _Reach(surface, bound, receiver)
        for statement in method.body:
            reach.visit(statement)
    surface.attributes = len(bound)
    return surface


class _Classes(ast.NodeVisitor):
    def __init__(self) -> None:
        self.holding: list[str] = []
        self.measured: dict[str, ClassSurface] = {}

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self.measured[".".join((*self.holding, node.name))] = _measure_class(node)
        self._inside(node)

    def visit_FunctionDef(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        self._inside(node)

    visit_AsyncFunctionDef = visit_FunctionDef

    def _inside(self, node: ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        self.holding.append(node.name)
        self.generic_visit(node)
        self.holding.pop()


def measure_classes(source: str) -> dict[str, ClassSurface]:
    classes = _Classes()
    classes.visit(ast.parse(source))
    return classes.measured

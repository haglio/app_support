from __future__ import annotations

import ast
import operator
from typing import NamedTuple

_WAIT_WORDS = frozenset({"timeout", "within", "patience", "wait", "waiting", "deadline", "budget"})
_A_CLOCK_HANDED_ON = frozenset({"clock", "now", "now_source", "sleep", "monotonic", "nap", "timer"})
_WAITING_ON_ITS_FIRST_ARGUMENT = frozenset({"wait", "join", "result", "settimeout", "qWait"})
_ARITHMETIC = {ast.Mult: operator.mul, ast.Add: operator.add, ast.Sub: operator.sub}

_ON_THE_WALL = frozenset({
    "time.sleep", "asyncio.sleep",
    *(f"time.{read}{ns}" for read in ("time", "monotonic", "perf_counter") for ns in ("", "_ns")),
    "datetime.datetime.now", "datetime.datetime.utcnow", "datetime.datetime.today", "datetime.date.today",
})


class Wait(NamedTuple):
    line: int
    written: str


def _imported(tree: ast.Module) -> dict[str, str]:
    held: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                held[alias.asname or alias.name] = alias.name
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            for alias in node.names:
                held[alias.asname or alias.name] = f"{node.module}.{alias.name}"
    return held


def _origin(node: ast.expr, held: dict[str, str]) -> str | None:
    if isinstance(node, ast.Name):
        return held.get(node.id)
    if isinstance(node, ast.Attribute):
        base = _origin(node.value, held)
        return f"{base}.{node.attr}" if base else None
    return None


def _names_a_wait(name: str) -> bool:
    return not _WAIT_WORDS.isdisjoint(name.lower().split("_"))


def _number(node: ast.expr, constants: dict[str, float]) -> float | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
        return node.value
    if isinstance(node, ast.Name):
        return constants.get(node.id)
    if isinstance(node, ast.BinOp) and type(node.op) in _ARITHMETIC:
        left, right = _number(node.left, constants), _number(node.right, constants)
        if left is not None and right is not None:
            return _ARITHMETIC[type(node.op)](left, right)
    return None


def _numbers_of_the_file(tree: ast.Module) -> dict[str, float]:
    constants: dict[str, float] = {}
    for node in tree.body:
        if isinstance(node, (ast.Assign, ast.AnnAssign)) and node.value is not None:
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            value = _number(node.value, constants)
            for target in targets:
                if isinstance(target, ast.Name) and value is not None:
                    constants[target.id] = value
    return constants


def _keeps_time_by_a_clock_it_is_handed(call: ast.Call, held: dict[str, str]) -> bool:
    return any(keyword.arg in _A_CLOCK_HANDED_ON and _origin(keyword.value, held) not in _ON_THE_WALL
               for keyword in call.keywords)


def _hands_a_number_as_a_wait(call: ast.Call, constants: dict[str, float], held: dict[str, str]) -> bool:
    if ast.unparse(call.func).endswith("TimeoutExpired") or _keeps_time_by_a_clock_it_is_handed(call, held):
        return False
    waits_first = isinstance(call.func, ast.Attribute) and call.func.attr in _WAITING_ON_ITS_FIRST_ARGUMENT
    return bool(waits_first and call.args and _number(call.args[0], constants)) or any(
        keyword.arg and _names_a_wait(keyword.arg) and _number(keyword.value, constants)
        for keyword in call.keywords)


def _is_a_wait_of_pytest_qt(call: ast.Call) -> bool:
    func = call.func
    return (isinstance(func, ast.Attribute) and func.attr.startswith("wait")
            and isinstance(func.value, ast.Name) and func.value.id == "qtbot")


def _is_a_string(node: ast.expr) -> bool:
    return isinstance(node, ast.Constant) and isinstance(node.value, str)


def _where_the_patched_name_is(call: ast.Call) -> int | None:
    patcher = ast.unparse(call.func).removeprefix("unittest.").removeprefix("mock.")
    if patcher == "patch":
        return 0
    if patcher == "patch.object":
        return 1
    if patcher == "monkeypatch.setattr" and call.args:
        return 0 if _is_a_string(call.args[0]) else 1
    return None


def _patches_a_wait_to_a_number(call: ast.Call, constants: dict[str, float]) -> bool:
    at = _where_the_patched_name_is(call)
    if at is None or len(call.args) <= at or not _is_a_string(call.args[at]):
        return False
    new = call.args[at + 1] if len(call.args) > at + 1 else next(
        (keyword.value for keyword in call.keywords if keyword.arg == "new"), None)
    return (_names_a_wait(call.args[at].value.rsplit(".", 1)[-1])
            and new is not None and bool(_number(new, constants)))


def _reads_of_the_wall(tree: ast.Module, held: dict[str, str], calls: list[ast.Call]) -> list[ast.expr]:
    called = {id(call.func): call for call in calls}
    return [called.get(id(node), node) for node in ast.walk(tree)
            if isinstance(node, (ast.Name, ast.Attribute)) and _origin(node, held) in _ON_THE_WALL]


def _waiting_calls(calls: list[ast.Call], held: dict[str, str], constants: dict[str, float]) -> list[ast.Call]:
    return [call for call in calls if _is_a_wait_of_pytest_qt(call) or _hands_a_number_as_a_wait(call, constants, held)
            or _patches_a_wait_to_a_number(call, constants)]


def waits_in(source: str) -> list[Wait]:
    tree = ast.parse(source)
    held, constants = _imported(tree), _numbers_of_the_file(tree)
    calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call)]
    found = {id(node): node for node in (*_reads_of_the_wall(tree, held, calls), *_waiting_calls(calls, held, constants))}
    return sorted(Wait(node.lineno, ast.unparse(node)) for node in found.values())

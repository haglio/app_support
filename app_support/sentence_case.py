from __future__ import annotations

import ast
import re
from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import NamedTuple

KEY_NAMES = frozenset((
    "Esc", "Enter", "Return", "Space", "Tab", "Shift", "Ctrl", "Alt", "Backspace", "Delete", "Del",
    "Home", "End", "Insert", "PgUp", "PgDn", "Up", "Down", "Left", "Right",
))
_SENTENCE_STARTS = re.compile(r"(?:^|;;|[.!?:|]\s+|\s[-–—]\s+|[\"“(\n]|\{[^}]*\})")
_WORD = re.compile(r"(?<![%A-Za-z0-9])[A-Za-z][A-Za-z0-9'+]*")


def _is_a_name_by_its_shape(word: str) -> bool:
    return word == "I" or "+" in word or any(c.isupper() or c.isdigit() for c in word[1:])


def capitalized_words(text: str, names: Iterable[str]) -> list[str]:
    if "\\" in text:
        return []
    for name in sorted(names, key=len, reverse=True):
        text = re.sub(rf"\b{re.escape(name)}\b", "name", text)
    found = []
    for piece in _SENTENCE_STARTS.split(text):
        for index, match in enumerate(_WORD.finditer(piece)):
            word = match.group(0)
            if index and word[0].isupper() and word not in KEY_NAMES and not _is_a_name_by_its_shape(word):
                found.append(word)
    return found


CAPTION_CALLS = frozenset((
    "QPushButton", "QToolButton", "QCheckBox", "QRadioButton", "QLabel", "QGroupBox", "QAction",
    "QMenu", "addAction", "addMenu", "addTab", "insertTab", "setTabText", "addItem", "addItems",
    "setText", "setToolTip", "setStatusTip", "setWhatsThis", "setWindowTitle", "setTitle",
    "setPlaceholderText", "setHeaderLabels", "setInformativeText", "getText", "getItem", "getInt",
    "getDouble", "getOpenFileName", "getOpenFileNames", "getSaveFileName", "getExistingDirectory",
))
MESSAGE_BOX_CALLS = frozenset(("information", "warning", "critical", "question"))
CAPTION_KEYWORDS = frozenset(("text", "label", "title", "tooltip", "tool_tip", "caption", "heading",
                              "placeholder", "hint"))
_CAPTION_NAME = re.compile(r"(?:CAPTION|LABEL|TITLE|TOOLTIP|TOOL_TIP|HEADING|PLACEHOLDER|TEXT)S?$")


class Caption(NamedTuple):
    where: str
    line: int
    text: str


def _strings(node: ast.AST) -> Iterator[ast.Constant]:
    for inner in ast.walk(node):
        if isinstance(inner, ast.Constant) and isinstance(inner.value, str):
            yield inner


def _called(node: ast.Call) -> str:
    if not isinstance(node.func, ast.Attribute):
        return getattr(node.func, "id", "")
    if node.func.attr in MESSAGE_BOX_CALLS:
        return node.func.attr if getattr(node.func.value, "id", "") == "QMessageBox" else ""
    return node.func.attr


def _target_names(node: ast.Assign | ast.AnnAssign) -> list[str]:
    targets = node.targets if isinstance(node, ast.Assign) else [node.target]
    return [getattr(target, "id", getattr(target, "attr", "")) for target in targets]


def _caption_nodes(tree: ast.AST, calls: frozenset[str]) -> list[ast.Constant]:
    return list({id(node): node for node in _each_caption_node(tree, calls)}.values())


def _each_caption_node(tree: ast.AST, calls: frozenset[str]) -> Iterator[ast.Constant]:
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            if _called(node) in calls:
                for argument in node.args:
                    yield from _strings(argument)
            for keyword in node.keywords:
                if keyword.arg and keyword.arg.lower() in CAPTION_KEYWORDS:
                    yield from _strings(keyword.value)
        elif isinstance(node, (ast.Assign, ast.AnnAssign)) and node.value is not None:
            if any(_CAPTION_NAME.search(name.upper()) for name in _target_names(node)):
                yield from _strings(node.value)


def _place(node: ast.Constant) -> tuple[int, int]:
    return node.lineno, node.col_offset


def captions(folders: Iterable[Path], calls: Iterable[str] = ()) -> list[Caption]:
    every_call = CAPTION_CALLS | MESSAGE_BOX_CALLS | frozenset(calls)
    found = []
    for folder in folders:
        for path in sorted(folder.rglob("*.py")):
            where = path.relative_to(folder.parent).as_posix()
            tree = ast.parse(path.read_text(encoding="utf-8"))
            nodes = sorted(_caption_nodes(tree, every_call), key=_place)
            found += [Caption(where, node.lineno, node.value) for node in nodes]
    return found


def assert_captions_are_sentence_case(folders: Iterable[Path], names: Iterable[str] = (),
                                      calls: Iterable[str] = ()) -> None:
    names = tuple(names)
    every = captions(folders, calls)
    other_captions = {caption.text for caption in every
                      if 2 <= len(caption.text.split()) <= 5 and not capitalized_words(caption.text, names)}
    broken = [f"{caption.where}:{caption.line} {caption.text!r} capitalizes {', '.join(words)}"
              for caption in every
              if (words := capitalized_words(caption.text, (*names, *(other_captions - {caption.text}))))]
    assert not broken, (
        "On-screen text is in sentence case: only the first word of a sentence and a name take a "
        "capital. Lowercase each word named, or, if it is a name, add it to [tool.haglio.sentence-case] "
        "names in pyproject.toml:\n  " + "\n  ".join(broken))

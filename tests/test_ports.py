"""The ports the family claims, held to the numbers already on the wire."""
from __future__ import annotations

import ast
import re
from pathlib import Path

from app_support import ports

_CLAIMED = {name: value for name, value in vars(ports).items() if name.isupper()}


def test_the_numbers_are_the_ones_the_running_configs_already_say():
    """Pinned as literals, not derived: a config file written a year ago still
    says 50557, and so does a broker started before this constant existed."""
    assert ports.TCODE_UDP == 50557
    assert ports.GENAU_UDP == 50555
    assert ports.AUDIO_COMPANION == 50556
    assert ports.USERSCRIPT_HTTP == 8770


def test_no_two_agreements_claim_the_same_port():
    """The one mistake a scattered list could not catch: the fifth port added
    lands on a number a running app already binds, and only the loser of the
    bind finds out."""
    assert len(set(_CLAIMED.values())) == len(_CLAIMED)


def test_every_port_is_one_an_ordinary_process_can_bind():
    for name, port in _CLAIMED.items():
        assert 1024 < port < 65536, name


def _what_each_port_says() -> dict[str, str]:
    """Each constant paired with the string standing under it in the source.

    Read off the source because a string under an assignment is documentation to
    every reader and to nothing at runtime: Python evaluates it and throws it
    away, so `vars()` cannot see whether a port says anything at all.
    """
    module = ast.parse(Path(ports.__file__).read_text(encoding="utf-8"))
    said: dict[str, str] = {}
    name = None
    for node in module.body:
        if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name):
            name = node.targets[0].id
            said[name] = ""
        elif (name and isinstance(node, ast.Expr)
                and isinstance(node.value, ast.Constant)
                and isinstance(node.value.value, str)):
            said[name] = node.value.value
            name = None
    return said


def test_every_port_says_who_listens_and_who_sends():
    """The whole value of one list over five literals. A number with nobody
    named beside it is the shape these were in before, in a nicer file."""
    said = _what_each_port_says()
    assert set(said) == set(_CLAIMED)
    for name, text in said.items():
        first = text.strip().splitlines()[0] if text.strip() else ""
        assert re.fullmatch(r".+ listens; .+ sends?\.", first), f"{name}: {first!r}"

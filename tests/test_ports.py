from __future__ import annotations

import re

from app_support import ports

_CLAIMED = {name: value for name, value in vars(ports).items() if isinstance(value, int)}


def test_the_numbers_are_the_ones_the_running_configs_already_say():
    assert ports.TCODE_UDP == 50557
    assert ports.GENAU_UDP == 50555
    assert ports.AUDIO_COMPANION == 50556
    assert ports.USERSCRIPT_HTTP == 8770
    assert ports.OSR2_SLOT == 50558


def test_no_two_agreements_claim_the_same_port_so_every_port_the_family_binds_is_listed_even_one_repos_own():
    assert len(set(_CLAIMED.values())) == len(_CLAIMED)


def test_every_port_is_one_an_ordinary_process_can_bind():
    for name, port in _CLAIMED.items():
        assert 1024 < port < 65536, name


def test_every_port_says_who_listens_and_who_sends_since_a_datagram_to_a_wrong_port_fails_without_a_sign():
    said = ports.WHO_MEETS_ON
    assert set(said) == set(_CLAIMED)
    for name, text in said.items():
        assert re.fullmatch(r".+ listens; .+ sends?\.", text), f"{name}: {text!r}"

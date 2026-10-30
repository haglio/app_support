from __future__ import annotations

import pytest

from app_support.gates import Checkout
from app_support.launcher import assert_launchers_match_their_specs

pytestmark = pytest.mark.repo_check


def test_every_launcher_is_what_its_spec_renders(pytestconfig):
    assert_launchers_match_their_specs(Checkout.of(pytestconfig).root)

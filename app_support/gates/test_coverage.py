from __future__ import annotations

import pytest

from app_support.coverage_gate import NotUnitTested, assert_config_is_the_familys
from app_support.gates import Checkout

pytestmark = pytest.mark.repo_check


def test_the_coverage_config_is_the_familys(pytestconfig):
    checkout = Checkout.of(pytestconfig)
    numbers = checkout.numbers("coverage")
    not_unit_tested = tuple(NotUnitTested(**entry) for entry in numbers.get("not-unit-tested", ()))
    assert_config_is_the_familys(checkout.root / ".coveragerc", not_unit_tested, numbers.get("max-pragmas", 0))

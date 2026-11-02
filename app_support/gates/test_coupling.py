from __future__ import annotations

import pytest

from app_support.coupling import assert_no_app_imports_another, assert_within_ceilings, measure
from app_support.gates import Checkout

pytestmark = pytest.mark.repo_check


def test_no_count_has_moved_from_its_ceiling(pytestconfig):
    checkout = Checkout.of(pytestconfig)
    ceilings = checkout.numbers("coupling")
    if ceilings:
        assert_within_ceilings(measure(checkout), ceilings)


def test_no_app_imports_another_apps_code(pytestconfig):
    assert_no_app_imports_another(measure(Checkout.of(pytestconfig)))

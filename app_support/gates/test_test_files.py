from __future__ import annotations

import pytest

from app_support.gates import Checkout
from app_support.misnamed_tests import assert_every_file_holding_tests_is_named_test

pytestmark = pytest.mark.repo_check


def test_no_file_of_tests_goes_unrun(pytestconfig):
    assert_every_file_holding_tests_is_named_test(Checkout.of(pytestconfig).tests)

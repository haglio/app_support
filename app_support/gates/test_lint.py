from __future__ import annotations

import pytest

from app_support.gates import Checkout
from app_support.lint import assert_config_is_the_familys, assert_lint_is_clean

pytestmark = pytest.mark.repo_check


def test_the_ruff_config_is_the_familys(pytestconfig):
    assert_config_is_the_familys(Checkout.of(pytestconfig).root / "ruff.toml")


def test_ruff_finds_nothing(pytestconfig):
    checkout = Checkout.of(pytestconfig)
    assert_lint_is_clean(checkout.root, *checkout.packages, *checkout.tools, checkout.tests)

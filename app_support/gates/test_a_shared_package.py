from __future__ import annotations

import pytest

from app_support.dependencies import assert_the_version_comes_from_the_tag
from app_support.gates import Checkout

pytestmark = pytest.mark.repo_check


def test_the_version_comes_from_the_tag(pytestconfig):
    assert_the_version_comes_from_the_tag(Checkout.of(pytestconfig).pyproject)

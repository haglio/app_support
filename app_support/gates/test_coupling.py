from __future__ import annotations

import pytest

from app_support.coupling import assert_no_app_imports_another
from app_support.gates import Checkout

pytestmark = pytest.mark.repo_check


def test_no_app_imports_another_apps_code(pytestconfig):
    assert_no_app_imports_another(Checkout.of(pytestconfig))

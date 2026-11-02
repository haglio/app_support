from __future__ import annotations

import pytest

from app_support.gates import Checkout, baseline

pytestmark = pytest.mark.repo_check


@pytest.mark.parametrize("count", baseline.COUNTS, ids=lambda count: count.section)
def test_no_baseline_entry_has_moved(pytestconfig, count: baseline.Count):
    baseline.assert_count_holds(Checkout.of(pytestconfig), count)


def test_no_baseline_entry_stands_above_where_main_has_it(pytestconfig):
    baseline.assert_nothing_stands_above_main(Checkout.of(pytestconfig))

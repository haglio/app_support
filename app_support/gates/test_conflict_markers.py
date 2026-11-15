from __future__ import annotations

import pytest

from app_support.conflict_markers import assert_no_commit_holds_a_leftover
from app_support.gates import Checkout

pytestmark = pytest.mark.repo_check


def test_no_commit_this_branch_adds_holds_a_merge_conflicts_markers(pytestconfig):
    assert_no_commit_holds_a_leftover(Checkout.of(pytestconfig).root)

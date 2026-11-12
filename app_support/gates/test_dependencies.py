from __future__ import annotations

import pytest

from app_support.dependencies import (
    assert_every_dependency_is_bounded,
    assert_every_import_is_declared,
    assert_every_sibling_is_declared,
    assert_every_sibling_is_pinned,
    assert_the_declared_floor_is_the_one_the_gate_runs,
)
from app_support.gates import Checkout

pytestmark = pytest.mark.repo_check


def test_every_third_party_import_is_declared(pytestconfig):
    checkout = Checkout.of(pytestconfig)
    assert_every_import_is_declared(checkout.root, checkout.ships, checkout.pyproject,
                                    local=checkout.own_names)


def test_every_requirement_has_an_upper_bound(pytestconfig):
    checkout = Checkout.of(pytestconfig)
    assert_every_dependency_is_bounded(
        checkout.pyproject, allowing=checkout.numbers("dependencies").get("unbounded", ()))


def test_every_sibling_this_repo_needs_is_declared(pytestconfig):
    checkout = Checkout.of(pytestconfig)
    whitelist = (checkout.whitelist,) if checkout.whitelist and checkout.whitelist.suffix == ".py" else ()
    assert_every_sibling_is_declared(
        checkout.root, (*checkout.code, checkout.tests, *whitelist), checkout.pyproject)


def test_every_sibling_is_named_at_a_tag(pytestconfig):
    assert_every_sibling_is_pinned(Checkout.of(pytestconfig).pyproject)


def test_the_declared_floor_is_the_one_the_gate_runs(pytestconfig):
    checkout = Checkout.of(pytestconfig)
    assert_the_declared_floor_is_the_one_the_gate_runs(
        checkout.pyproject, checkout.root / ".github" / "workflows" / "merge-gate.yml")

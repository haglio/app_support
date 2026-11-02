from __future__ import annotations

import sys

import pytest

from app_support import launcher_contract
from app_support.gates import Checkout
from app_support.launcher import assert_launchers_match_their_specs

pytestmark = pytest.mark.repo_check


def test_every_launcher_is_what_its_spec_renders(pytestconfig):
    assert_launchers_match_their_specs(Checkout.of(pytestconfig).root)


@pytest.mark.skipif(sys.platform != "win32", reason="the Windows script host")
def test_every_launcher_reports_what_its_spec_says_under_the_real_script_host(pytestconfig):
    launcher_contract.assert_every_launcher_reports_its_spec(Checkout.of(pytestconfig).root)


def test_what_every_launcher_runs_is_in_this_checkout(pytestconfig):
    launcher_contract.assert_what_every_launcher_runs_is_there(Checkout.of(pytestconfig).root)


def test_every_launcher_keeps_a_log_unless_this_repo_lists_it(pytestconfig):
    checkout = Checkout.of(pytestconfig)
    launcher_contract.assert_every_launcher_keeps_a_log(
        checkout.root, without=checkout.numbers("launcher-gate").get("without-a-log", ()))


def test_what_a_shortcut_or_a_task_starts_runs_on_its_own_venv(pytestconfig):
    launcher_contract.assert_what_a_shortcut_or_a_task_starts_runs_on_its_own_venv(Checkout.of(pytestconfig).root)


def test_a_branch_can_be_tried_out_of_its_own_checkout(pytestconfig):
    checkout = Checkout.of(pytestconfig)
    if not checkout.is_a_library:
        launcher_contract.assert_a_branch_can_be_tried(checkout.root)

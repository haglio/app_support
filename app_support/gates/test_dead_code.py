from __future__ import annotations

from pathlib import Path
from typing import NamedTuple

import pytest

from app_support import unread
from app_support.dead_code import (
    assert_no_dead_code,
    assert_no_function_takes_an_argument_it_never_reads,
    assert_nothing_is_imported_or_assigned_and_left_unread,
    assert_whitelist_is_live,
    tracked_python,
)
from app_support.gates import Checkout
from app_support.siblings import checkouts_that_import

pytestmark = pytest.mark.repo_check


def _allowed(checkout: Checkout, kind: str) -> tuple[str, ...]:
    return tuple(checkout.numbers("dead-code").get(f"unread-{kind}", ()))


def _read(checkout: Checkout) -> tuple[Path, ...]:
    return (*checkout.code, checkout.tests) if checkout.is_a_library else checkout.code


class _Scan(NamedTuple):
    targets: tuple[Path, ...]
    each_alone: bool
    callers: tuple[Path, ...]


def _vulture(checkout: Checkout) -> _Scan:
    numbers = checkout.numbers("dead-code")
    each_alone = numbers.get("each-package-alone", False)
    if not numbers.get("apps-are-callers", False):
        return _Scan(_read(checkout), each_alone, ())
    apps = checkouts_that_import(*checkout.own_names, near=checkout.tests / "test_dead_code.py")
    if not apps:
        pytest.skip("no checkout beside this one imports it, so there are no callers to read")
    callers = (checkout.tests, *(path for app in apps for path in tracked_python(app)))
    return _Scan(checkout.code, each_alone, callers)


def test_no_dead_code(pytestconfig):
    checkout = Checkout.of(pytestconfig)
    scan = _vulture(checkout)
    assert_no_dead_code(*scan.targets, whitelist=checkout.whitelist, each_alone=scan.each_alone,
                        callers=scan.callers)


def test_the_whitelist_still_suppresses_what_it_claims_to(pytestconfig):
    checkout = Checkout.of(pytestconfig)
    if checkout.whitelist is not None:
        scan = _vulture(checkout)
        assert_whitelist_is_live(*scan.targets, whitelist=checkout.whitelist,
                                 each_alone=scan.each_alone, callers=scan.callers)


def test_nothing_is_imported_or_assigned_and_left_unread(pytestconfig):
    checkout = Checkout.of(pytestconfig)
    assert_nothing_is_imported_or_assigned_and_left_unread(checkout.root, *checkout.code, checkout.tests)


def test_no_function_takes_an_argument_it_never_reads(pytestconfig):
    checkout = Checkout.of(pytestconfig)
    assert_no_function_takes_an_argument_it_never_reads(
        checkout.root, *checkout.code, allowing=_allowed(checkout, "arguments"))


def test_no_module_level_constant_goes_unread(pytestconfig):
    checkout = Checkout.of(pytestconfig)
    unread.assert_no_module_constant_goes_unread(
        checkout.root, _read(checkout), allowing=_allowed(checkout, "constants"))


def test_no_constructor_parameter_is_stored_and_never_read(pytestconfig):
    checkout = Checkout.of(pytestconfig)
    unread.assert_no_constructor_parameter_is_stored_and_never_read(
        checkout.root, _read(checkout), allowing=_allowed(checkout, "constructor-parameters"))


def test_no_dataclass_field_goes_unread(pytestconfig):
    checkout = Checkout.of(pytestconfig)
    unread.assert_no_dataclass_field_goes_unread(
        checkout.root, _read(checkout), allowing=_allowed(checkout, "dataclass-fields"))


def test_every_declared_command_line_option_is_read(pytestconfig):
    checkout = Checkout.of(pytestconfig)
    unread.assert_every_argparse_option_is_read(
        checkout.root, _read(checkout), allowing=_allowed(checkout, "command-line-options"))


def test_no_test_helper_is_written_and_never_called(pytestconfig):
    checkout = Checkout.of(pytestconfig)
    unread.assert_no_test_helper_is_written_and_never_called(
        checkout.root, checkout.tests, allowing=_allowed(checkout, "test-helpers"))

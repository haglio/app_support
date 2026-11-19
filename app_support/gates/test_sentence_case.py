from __future__ import annotations

import pytest

from app_support.gates import Checkout
from app_support.sentence_case import assert_captions_are_sentence_case

pytestmark = pytest.mark.repo_check


def test_the_text_on_screen_is_in_sentence_case(pytestconfig):
    checkout = Checkout.of(pytestconfig)
    declared = checkout.numbers("sentence-case")
    assert_captions_are_sentence_case(checkout.packages, names=declared.get("names", ()),
                                      calls=declared.get("calls", ()))

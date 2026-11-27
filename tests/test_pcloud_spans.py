from __future__ import annotations

import pytest

from app_support.pcloud.spans import asked_span


@pytest.mark.parametrize(("header", "span"), [
    (None, (0, 40)),
    ("bytes=10-20", (10, 21)),
    ("bytes=10-", (10, 40)),
    ("bytes=-5", (35, 40)),
    ("bytes=30-99", (30, 40)),
])
def test_a_players_range_names_the_bytes_it_wants_from_the_first_to_the_last_both_counted(header, span):
    assert asked_span(header, 40) == span

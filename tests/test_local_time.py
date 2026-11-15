from __future__ import annotations

from datetime import UTC, date, datetime, timedelta, timezone

from app_support.local_time import when_words

PACIFIC = timezone(timedelta(hours=-8))
NOW = datetime(2026, 11, 14, 19, 30, tzinfo=PACIFIC)


def test_a_moment_today_reads_today_in_local_time():
    made = datetime(2026, 11, 15, 2, 5, 9, tzinfo=UTC)
    assert when_words(made, NOW) == "Today 2026-11-14 18:05:09"


def test_a_moment_yesterday_reads_yesterday():
    assert when_words(datetime(2026, 11, 13, 23, 59, 59, tzinfo=PACIFIC), NOW) == (
        "Yesterday 2026-11-13 23:59:59")


def test_an_older_moment_reads_its_day_of_the_week():
    assert when_words(datetime(2026, 11, 12, 8, 0, tzinfo=PACIFIC), NOW) == (
        "Thu 2026-11-12 08:00:00")


def test_a_stored_stamp_without_a_zone_is_utc():
    assert when_words("2026-11-15 02:05:09", NOW) == "Today 2026-11-14 18:05:09"


def test_a_stored_stamp_with_a_zone_keeps_it():
    assert when_words("2026-11-12T16:00:00+00:00", NOW) == "Thu 2026-11-12 08:00:00"


def test_a_date_alone_reads_without_a_clock():
    assert when_words("2026-11-13", NOW) == "Yesterday 2026-11-13"
    assert when_words(date(2026, 11, 10), NOW) == "Tue 2026-11-10"


def test_a_stamp_that_is_no_time_reads_as_it_was_stored():
    assert when_words("last spring", NOW) == "last spring"
    assert when_words("", NOW) == ""


def test_now_defaults_to_the_computers_clock():
    assert when_words(datetime.now().astimezone()).startswith("Today ")

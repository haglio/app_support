from __future__ import annotations

from datetime import UTC, date, datetime, timedelta


def when_words(when: datetime | date | str, now: datetime | None = None) -> str:
    moment = _moment_of(when) if isinstance(when, str) else when
    if moment is None:
        return str(when)
    today = (now or datetime.now().astimezone()).date()
    if isinstance(moment, datetime):
        local = moment.astimezone(now.tzinfo if now else None)
        return f"{_day_word(local.date(), today)}, {local:%H:%M} on {_date_words(local.date())}"
    return f"{_day_word(moment, today)}, {_date_words(moment)}"


def _date_words(day: date) -> str:
    return f"{day.day} {day:%b}, {day.year}"


def _moment_of(stamp: str) -> datetime | date | None:
    try:
        if len(stamp.strip()) == len("2026-01-01"):
            return date.fromisoformat(stamp.strip())
        moment = datetime.fromisoformat(stamp.strip())
    except ValueError:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=UTC)


def _day_word(day: date, today: date) -> str:
    if day == today:
        return "Today"
    if day == today - timedelta(days=1):
        return "Yesterday"
    return f"{day:%a}"

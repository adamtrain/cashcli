"""Date helpers: ISO parsing, clamped month arithmetic, month ends."""

from __future__ import annotations

import calendar
import os
from collections.abc import Iterator
from datetime import date, timedelta

from cashcli.errors import CashError


def today() -> date:
    """Today's date, overridable with CASHCLI_TODAY=YYYY-MM-DD (tests, reproducible runs)."""
    override = os.environ.get("CASHCLI_TODAY")
    if override:
        return parse_date(override)
    return date.today()


def month_start(d: date) -> date:
    return d.replace(day=1)


def parse_date(text: str | date) -> date:
    if isinstance(text, date):
        return text
    try:
        return date.fromisoformat(str(text).strip())
    except ValueError as exc:
        raise CashError(f"invalid date {text!r}; expected YYYY-MM-DD", "invalid_date") from exc


def iso(d: date) -> str:
    return d.isoformat()


def days_in_month(year: int, month: int) -> int:
    return calendar.monthrange(year, month)[1]


def add_months(d: date, months: int) -> date:
    """Add months, clamping the day to the target month's length (Jan 31 + 1 -> Feb 28)."""
    total = d.year * 12 + (d.month - 1) + months
    year, month = divmod(total, 12)
    month += 1
    return date(year, month, min(d.day, days_in_month(year, month)))


def month_end(d: date) -> date:
    return date(d.year, d.month, days_in_month(d.year, d.month))


def is_month_end(d: date) -> bool:
    return d.day == days_in_month(d.year, d.month)


def daterange(start: date, end: date) -> Iterator[date]:
    """Inclusive range of dates."""
    d = start
    one = timedelta(days=1)
    while d <= end:
        yield d
        d += one


def months_between(start: date, end: date) -> int:
    """Whole-month count used for --months style windows (end - start), floor."""
    return (
        (end.year - start.year) * 12 + (end.month - start.month) - (1 if end.day < start.day else 0)
    )

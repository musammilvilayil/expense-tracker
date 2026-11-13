"""Autopay rules: schedule math for recurring payments."""
import calendar
from datetime import date, datetime, timedelta

FREQUENCIES = ("weekly", "monthly", "quarterly", "yearly")


def _add_months(d: date, months: int, anchor_day: int) -> date:
    y, m = divmod(d.year * 12 + d.month - 1 + months, 12)
    m += 1
    return date(y, m, min(anchor_day, calendar.monthrange(y, m)[1]))


def advance(d: date, frequency: str, anchor_day: int) -> date:
    """Next due date after d. anchor_day keeps 31st-of-month rules from drifting."""
    if frequency == "weekly":
        return d + timedelta(days=7)
    step = {"monthly": 1, "quarterly": 3, "yearly": 12}[frequency]
    return _add_months(d, step, anchor_day)


def due_dates(next_date: str, frequency: str, anchor_day: int, today: date, limit=60):
    """All occurrences from next_date up to and including today, plus the following date."""
    d = datetime.strptime(next_date, "%Y-%m-%d").date()
    out = []
    while d <= today and len(out) < limit:
        out.append(d)
        d = advance(d, frequency, anchor_day)
    return out, d

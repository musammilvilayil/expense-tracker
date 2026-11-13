"""Detect recurring transactions (subscriptions) and upcoming renewals."""
from collections import defaultdict
from datetime import date, datetime, timedelta
from statistics import median

from .preprocess import normalize_merchant

# (label, min_days, max_days, nominal_days, monthly_multiplier)
PERIODS = [
    ("weekly", 6, 8, 7, 52 / 12),
    ("monthly", 26, 35, 30, 1),
    ("quarterly", 85, 95, 91, 1 / 3),
    ("yearly", 355, 375, 365, 1 / 12),
]


def _d(s):
    return datetime.strptime(s, "%Y-%m-%d").date()


def detect(transactions, amount_tolerance=0.15):
    """transactions: iterable of dicts with date/description/amount/type."""
    groups = defaultdict(list)
    for t in transactions:
        if t["type"] != "expense":
            continue
        key = normalize_merchant(t["description"])
        if key:
            groups[key].append(t)

    found = []
    for key, items in groups.items():
        if len(items) < 2:
            continue
        items.sort(key=lambda t: t["date"])
        dates = [_d(t["date"]) for t in items]
        gaps = [(b - a).days for a, b in zip(dates, dates[1:])]
        gap = median(gaps)
        period = next((p for p in PERIODS if p[1] <= gap <= p[2]), None)
        if not period:
            continue
        if any(not (period[1] - 3 <= g <= period[2] + 3) for g in gaps):
            continue
        amounts = [t["amount"] for t in items]
        mid = median(amounts)
        if any(abs(a - mid) / mid > amount_tolerance for a in amounts):
            continue
        last = dates[-1]
        found.append({
            "name": items[-1]["description"],
            "frequency": period[0],
            "amount": round(items[-1]["amount"], 2),
            "monthly_cost": round(items[-1]["amount"] * period[4], 2),
            "occurrences": len(items),
            "last_charged": last.isoformat(),
            "next_renewal": (last + timedelta(days=period[3])).isoformat(),
            "category": items[-1].get("category"),
        })
    found.sort(key=lambda s: s["next_renewal"])
    return found


def upcoming(subs, today=None, within_days=7):
    today = today or date.today()
    limit = today + timedelta(days=within_days)
    return [s for s in subs if today <= _d(s["next_renewal"]) <= limit]

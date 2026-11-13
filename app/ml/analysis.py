"""Spending analysis, anomaly detection, budgets and recommendations."""
from collections import defaultdict
from statistics import median


def summarize(transactions, prefix=None):
    """prefix filters by date string: '2026-11' for a month, '2026' for a year."""
    rows = [t for t in transactions if not prefix or t["date"].startswith(prefix)]
    income = sum(t["amount"] for t in rows if t["type"] == "income")
    expense = sum(t["amount"] for t in rows if t["type"] == "expense")
    by_cat = defaultdict(float)
    by_month = defaultdict(lambda: {"income": 0.0, "expense": 0.0})
    for t in rows:
        if t["type"] == "expense":
            by_cat[t["category"] or "Other"] += t["amount"]
        by_month[t["date"][:7]][t["type"]] += t["amount"]
    savings = income - expense
    return {
        "income": round(income, 2),
        "expense": round(expense, 2),
        "savings": round(savings, 2),
        "savings_rate": round(savings / income * 100, 1) if income else 0.0,
        "by_category": {k: round(v, 2) for k, v in sorted(by_cat.items(), key=lambda kv: -kv[1])},
        "by_month": {m: {k: round(v, 2) for k, v in d.items()} for m, d in sorted(by_month.items())},
        "count": len(rows),
    }


def find_anomalies(transactions, threshold=3.5, min_samples=5):
    """Flag expenses far above the typical amount for their category.

    Uses a robust (median/MAD) z-score so outliers don't hide themselves.
    """
    by_cat = defaultdict(list)
    for t in transactions:
        if t["type"] == "expense":
            by_cat[t["category"] or "Other"].append(t)
    out = []
    for cat, items in by_cat.items():
        if len(items) < min_samples:
            continue
        amounts = [t["amount"] for t in items]
        med = median(amounts)
        mad = median(abs(a - med) for a in amounts) or max(med * 0.1, 1.0)
        for t in items:
            z = 0.6745 * (t["amount"] - med) / mad
            if z > threshold:
                out.append({**{k: t[k] for k in ("id", "date", "description", "amount")},
                            "category": cat, "typical": round(med, 2), "score": round(z, 1)})
    out.sort(key=lambda a: -a["score"])
    return out


def budget_status(transactions, budgets, month):
    spent = defaultdict(float)
    for t in transactions:
        if t["type"] == "expense" and t["date"].startswith(month):
            spent[t["category"] or "Other"] += t["amount"]
    res = []
    for cat, limit in budgets.items():
        s = spent.get(cat, 0.0)
        pct = s / limit * 100 if limit else 0
        res.append({"category": cat, "limit": limit, "spent": round(s, 2), "percent": round(pct, 1),
                    "status": "over" if pct > 100 else "warning" if pct >= 80 else "ok"})
    return sorted(res, key=lambda r: -r["percent"])


def recommendations(transactions, subs, budgets, month):
    tips = []
    cur = summarize(transactions, month)
    y, m = map(int, month.split("-"))
    prev_month = f"{y - 1}-12" if m == 1 else f"{y}-{m - 1:02d}"
    prev = summarize(transactions, prev_month)

    if cur["income"] and cur["savings_rate"] < 20:
        tips.append(f"Your savings rate this month is {cur['savings_rate']}%. Aim for at least 20% by trimming discretionary spending.")
    if cur["expense"] and cur["by_category"]:
        top, amt = next(iter(cur["by_category"].items()))
        share = amt / cur["expense"] * 100
        if share > 40:
            tips.append(f"{top} makes up {share:.0f}% of this month's spending. Review it for savings.")
    for cat, amt in cur["by_category"].items():
        before = prev["by_category"].get(cat, 0)
        if before >= 500 and amt > before * 1.3:
            tips.append(f"{cat} spending is up {((amt / before) - 1) * 100:.0f}% versus last month.")
    sub_total = sum(s["monthly_cost"] for s in subs)
    if subs:
        tips.append(f"You have {len(subs)} recurring subscription(s) costing about {sub_total:.2f}/month ({sub_total * 12:.2f}/year). Cancel any you no longer use.")
        if cur["expense"] and sub_total / cur["expense"] > 0.25:
            tips.append("Subscriptions are over 25% of your monthly spending, which is high.")
    for b in budget_status(transactions, budgets, month):
        if b["status"] == "over":
            tips.append(f"You are over your {b['category']} budget ({b['spent']:.2f} of {b['limit']:.2f}).")
        elif b["status"] == "warning":
            tips.append(f"You have used {b['percent']:.0f}% of your {b['category']} budget.")
    if not tips:
        tips.append("Your spending looks healthy. Keep it up!")
    return tips

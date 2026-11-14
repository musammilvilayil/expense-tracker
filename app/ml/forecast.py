"""Spending / income forecasting.

For each series of completed monthly totals we backtest three simple models
(recent average, weighted average, damped linear trend), pick the one with
the lowest historical error and use its residual spread as an 80% range.
With under 3 months of data the range is wide and confidence is "low".
"""
import calendar
from collections import defaultdict
from datetime import date, timedelta
from math import sqrt
from statistics import mean

import numpy as np

from .preprocess import normalize_merchant
from .recurring import advance

Z80 = 1.28  # 80% interval multiplier


# ---------- month helpers ----------
def month_key(d: date) -> str:
    return d.strftime("%Y-%m")


def add_months(key: str, n: int) -> str:
    y, m = map(int, key.split("-"))
    idx = y * 12 + m - 1 + n
    return f"{idx // 12}-{idx % 12 + 1:02d}"


def month_range(start: str, end: str):
    out, k = [], start
    while k <= end:
        out.append(k)
        k = add_months(k, 1)
    return out


def monthly_series(txs, months, ttype, category=None):
    totals = defaultdict(float)
    for t in txs:
        if t["type"] != ttype:
            continue
        if category and (t["category"] or "Other") != category:
            continue
        totals[t["date"][:7]] += t["amount"]
    return [round(totals.get(m, 0.0), 2) for m in months]


# ---------- models ----------
def _average(v):
    return mean(v[-3:])


def _weighted(v):
    last = v[-6:]
    w = np.arange(1, len(last) + 1)
    return float(np.average(last, weights=w))


def _trend(v):
    last = v[-6:]
    if len(last) < 3:
        return mean(last)
    x = np.arange(len(last))
    slope, icpt = np.polyfit(x, last, 1)
    raw = icpt + slope * len(last)
    base = mean(last)
    pred = base + 0.7 * (raw - base)  # damp so one noisy slope doesn't explode
    return float(min(max(pred, 0.0), 2 * max(last)))


METHODS = {"weighted": _weighted, "average": _average, "trend": _trend}


def predict(values):
    """Predict the next value. Returns dict(pred, low, high, method, sd)."""
    n = len(values)
    if n == 0:
        return {"pred": 0.0, "low": 0.0, "high": 0.0, "method": "none", "sd": 0.0}
    if n < 3:
        pred = mean(values)
        sd = float(np.std(values)) if n == 2 else pred * 0.35
        sd = max(sd, pred * 0.15)
        method = "average"
    else:
        errors = {m: [] for m in METHODS}
        for t in range(2, n):
            for name, fn in METHODS.items():
                errors[name].append(values[t] - fn(values[:t]))
        best = min(METHODS, key=lambda m: mean(abs(e) for e in errors[m]))
        pred = METHODS[best](values)
        sd = sqrt(mean(e * e for e in errors[best]))
        sd = max(sd, pred * 0.05)
        method = best
    return {"pred": round(pred, 2), "low": round(max(0.0, pred - Z80 * sd), 2),
            "high": round(pred + Z80 * sd, 2), "method": method, "sd": sd}


def predict_horizon(values, horizon=3):
    """Iterative multi-step forecast; the range widens with the step."""
    vals, out, base_sd = list(values), [], None
    for step in range(1, horizon + 1):
        p = predict(vals)
        if base_sd is None:
            base_sd = p["sd"]
        sd = base_sd * sqrt(step)
        out.append({"pred": p["pred"], "low": round(max(0.0, p["pred"] - Z80 * sd), 2),
                    "high": round(p["pred"] + Z80 * sd, 2), "method": p["method"]})
        vals.append(p["pred"])
    return out


def confidence(n_months):
    return "low" if n_months < 3 else "medium" if n_months < 6 else "high"


# ---------- commitments ----------
def upcoming_commitments(autopay_rules, subs, today, days=30):
    """Known payments due in the next `days` days (autopay + detected subscriptions)."""
    limit = today + timedelta(days=days)
    items, seen = [], set()
    for r in autopay_rules:
        if not r["active"] or r["type"] != "expense":
            continue
        d = date.fromisoformat(r["next_date"])
        n = 0
        while d <= limit and n < 40:
            if d >= today:
                items.append({"name": r["description"], "amount": round(r["amount"], 2),
                              "date": d.isoformat(), "source": "autopay"})
            d = advance(d, r["frequency"], r["anchor_day"])
            n += 1
        seen.add(normalize_merchant(r["description"]))
    for s in subs:
        if normalize_merchant(s["name"]) in seen:
            continue
        d = date.fromisoformat(s["next_renewal"])
        if today <= d <= limit:
            items.append({"name": s["name"], "amount": round(s["amount"], 2),
                          "date": d.isoformat(), "source": "subscription"})
    items.sort(key=lambda i: i["date"])
    return items


# ---------- main entry ----------
def build(txs, budgets, autopay_rules, subs, today=None, horizon=3):
    today = today or date.today()
    cur = month_key(today)
    first = min((t["date"][:7] for t in txs), default=cur)
    done = month_range(first, add_months(cur, -1)) if first < cur else []
    done = done[-12:]

    exp_hist = monthly_series(txs, done, "expense")
    inc_hist = monthly_series(txs, done, "income")

    dim = calendar.monthrange(today.year, today.month)[1]
    mtd = round(sum(t["amount"] for t in txs if t["type"] == "expense" and t["date"].startswith(cur)), 2)
    run_rate = mtd / today.day * dim
    baseline = predict(exp_hist)["pred"] if exp_hist else None
    w = today.day / dim
    projected = round(w * run_rate + (1 - w) * baseline, 2) if baseline is not None else round(run_rate, 2)

    # Fall back to the current month's pace when there is no completed month yet.
    exp_series = exp_hist or ([projected] if mtd else [])
    inc_mtd = sum(t["amount"] for t in txs if t["type"] == "income" and t["date"].startswith(cur))
    inc_series = inc_hist or ([round(inc_mtd, 2)] if inc_mtd else [])
    n_months = len(exp_hist)

    f_months = [add_months(cur, i) for i in range(1, horizon + 1)]
    f_exp = predict_horizon(exp_series, horizon) if exp_series else []
    f_inc = predict_horizon(inc_series, horizon) if inc_series else []
    f_sav = []
    if f_exp and f_inc:
        f_sav = [{"pred": round(i["pred"] - e["pred"], 2),
                  "low": round(i["low"] - e["high"], 2), "high": round(i["high"] - e["low"], 2)}
                 for e, i in zip(f_exp, f_inc)]

    # per-category forecast (next month)
    cats = []
    cat_names = {t["category"] or "Other" for t in txs if t["type"] == "expense"}
    for c in cat_names:
        series = monthly_series(txs, done, "expense", c)
        if not any(series[-6:]):
            continue
        p = predict(series)
        last = series[-1] if series else 0.0
        change = round((p["pred"] - last) / last * 100, 1) if last else None
        limit = budgets.get(c)
        risk = None
        if limit:
            risk = "over" if p["pred"] > limit else "warning" if p["pred"] >= 0.8 * limit else "ok"
        cats.append({"category": c, "predicted": p["pred"], "low": p["low"], "high": p["high"],
                     "last_month": last, "change_pct": change, "budget": limit, "budget_risk": risk,
                     "method": p["method"]})
    cats.sort(key=lambda c: -c["predicted"])

    commitments = upcoming_commitments(autopay_rules, subs, today)
    result = {
        "history": {"months": done, "expense": exp_hist, "income": inc_hist},
        "forecast": {"months": f_months, "expense": f_exp, "income": f_inc, "savings": f_sav},
        "confidence": confidence(n_months), "months_of_data": n_months,
        "categories": cats,
        "current_month": {"month": cur, "spent_so_far": mtd, "projected": projected,
                          "usual": baseline, "days_left": dim - today.day},
        "commitments": commitments,
        "commitments_total": round(sum(c["amount"] for c in commitments), 2),
    }
    result["insights"] = _insights(result)
    return result


def _insights(r):
    tips = []
    fe, fs, conf = r["forecast"]["expense"], r["forecast"]["savings"], r["confidence"]
    if not fe:
        return ["Add some transactions to unlock forecasts."]
    nxt = fe[0]
    hist = r["history"]["expense"]
    msg = f"Next month you are likely to spend about {nxt['pred']:.2f} (likely range {nxt['low']:.2f} to {nxt['high']:.2f})"
    if hist and hist[-1]:
        ch = (nxt["pred"] - hist[-1]) / hist[-1] * 100
        if abs(ch) >= 5:
            msg += f", {'up' if ch > 0 else 'down'} {abs(ch):.0f}% from last month"
    tips.append(msg + ".")
    if fs and fs[0]["pred"] < 0:
        tips.append(f"Forecast spending exceeds income by {abs(fs[0]['pred']):.2f} next month. Consider trimming discretionary categories.")
    elif fs:
        tips.append(f"Projected savings next month: {fs[0]['pred']:.2f}.")
    for c in r["categories"]:
        if c["budget_risk"] == "over":
            tips.append(f"{c['category']} is forecast at {c['predicted']:.2f}, above your {c['budget']:.2f} budget.")
    rising = [c for c in r["categories"] if c["change_pct"] is not None and c["change_pct"] >= 25 and c["predicted"] - c["last_month"] >= 50]
    if rising:
        top = max(rising, key=lambda c: c["predicted"] - c["last_month"])
        tips.append(f"{top['category']} is trending up (+{top['change_pct']:.0f}% expected).")
    cm = r["current_month"]
    if cm["usual"] and cm["projected"] > cm["usual"] * 1.15 and cm["days_left"] > 0:
        tips.append(f"You are on pace to spend {cm['projected']:.2f} this month, above your usual {cm['usual']:.2f}.")
    if r["commitments_total"]:
        tips.append(f"{r['commitments_total']:.2f} is already committed to autopay and subscriptions in the next 30 days.")
    if conf == "low":
        tips.append("Forecast confidence is low: it improves once you have 3 or more full months of data.")
    return tips

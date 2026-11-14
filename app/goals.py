"""Savings goals with contributions, projections and status."""
from datetime import date, datetime, timedelta

from flask import Blueprint, jsonify, request, session

from .db import get_db
from .helpers import err, login_required, run_autopay, user_budgets, user_transactions
from .ml import forecast, subscriptions
from .ml.preprocess import clean_description

bp = Blueprint("goals", __name__)
DAYS_PER_MONTH = 30.44


def goal_view(goal, contribs, forecast_rate, today):
    saved = max(0.0, round(sum(c["amount"] for c in contribs), 2))
    target = goal["target_amount"]
    remaining = round(max(0.0, target - saved), 2)
    recent = sum(c["amount"] for c in contribs if c["date"] >= (today - timedelta(days=90)).isoformat() and c.get("note") != "Starting amount")
    rate, source = (recent / 3, "contributions") if recent > 0 else ((forecast_rate, "forecast") if forecast_rate and forecast_rate > 0 else (None, None))
    target_date = date.fromisoformat(goal["target_date"]) if goal["target_date"] else None
    months_left = max((target_date - today).days, 0) / DAYS_PER_MONTH if target_date else None
    required = None
    if target_date and remaining > 0:
        required = round(remaining / months_left, 2) if months_left and months_left > 0 else remaining
    projected = None
    if remaining > 0 and rate:
        projected = (today + timedelta(days=remaining / rate * DAYS_PER_MONTH)).isoformat()
    if remaining == 0:
        status = "achieved"
    elif target_date and target_date < today:
        status = "overdue"
    elif rate is None:
        status = "no_data"
    elif target_date:
        status = "on_track" if projected <= target_date.isoformat() else "behind"
    else:
        status = "in_progress"
    return {"id": goal["id"], "name": goal["name"], "target_amount": target, "target_date": goal["target_date"],
            "saved": saved, "remaining": remaining, "percent": round(min(100.0, saved / target * 100), 1),
            "required_monthly": required, "monthly_rate": round(rate, 2) if rate else None, "rate_source": source,
            "projected_date": projected, "status": status}


def all_goals(uid, today=None):
    today = today or date.today()
    db = get_db()
    goals = db.execute("SELECT * FROM goals WHERE user_id=? ORDER BY id", (uid,)).fetchall()
    if not goals:
        return []
    contribs = {}
    for c in db.execute("SELECT goal_id,amount,date,note FROM goal_contributions WHERE user_id=?", (uid,)):
        contribs.setdefault(c["goal_id"], []).append(dict(c))
    forecast_rate = None
    if any(not any(c["date"] >= (today - timedelta(days=90)).isoformat() and c.get("note") != "Starting amount" for c in contribs.get(g["id"], [])) for g in goals):
        run_autopay(uid)
        txs = user_transactions(uid)
        rules = [dict(r) for r in db.execute("SELECT description,amount,type,frequency,anchor_day,next_date,active FROM autopay WHERE user_id=?", (uid,))]
        f = forecast.build(txs, user_budgets(uid), rules, subscriptions.detect(txs), today=today, horizon=1)
        forecast_rate = f["forecast"]["savings"][0]["pred"] if f["forecast"]["savings"] else None
    return [goal_view(g, contribs.get(g["id"], []), forecast_rate, today) for g in goals]


@bp.get("/api/goals")
@login_required
def list_goals():
    return jsonify(all_goals(session["user_id"]))


@bp.post("/api/goals")
@login_required
def create_goal():
    d = request.get_json(silent=True) or {}
    name = clean_description(d.get("name", ""))
    try:
        target = round(float(d.get("target_amount")), 2)
        tdate = datetime.strptime(d["target_date"], "%Y-%m-%d").date().isoformat() if d.get("target_date") else None
        initial = round(float(d.get("initial") or 0), 2)
    except (TypeError, ValueError):
        return err("target amount must be a number and the date must be YYYY-MM-DD")
    if not name or target <= 0 or initial < 0:
        return err("a name and a positive target amount are required")
    uid, db = session["user_id"], get_db()
    if db.execute("SELECT COUNT(*) FROM goals WHERE user_id=?", (uid,)).fetchone()[0] >= 20:
        return err("you can have up to 20 goals", 409)
    cur = db.execute("INSERT INTO goals(user_id,name,target_amount,target_date) VALUES(?,?,?,?)", (uid, name, target, tdate))
    if initial:
        db.execute("INSERT INTO goal_contributions(goal_id,user_id,amount,date,note) VALUES(?,?,?,?,?)",
                   (cur.lastrowid, uid, initial, date.today().isoformat(), "Starting amount"))
    db.commit()
    return jsonify(ok=True, id=cur.lastrowid), 201


def _own_goal(gid):
    return get_db().execute("SELECT * FROM goals WHERE id=? AND user_id=?", (gid, session["user_id"])).fetchone()


@bp.post("/api/goals/<int:gid>/contributions")
@login_required
def add_contribution(gid):
    if not _own_goal(gid):
        return err("not found", 404)
    d = request.get_json(silent=True) or {}
    try:
        amount = round(float(d.get("amount")), 2)
        when = datetime.strptime(d.get("date") or date.today().isoformat(), "%Y-%m-%d").date().isoformat()
    except (TypeError, ValueError):
        return err("amount must be a number and the date must be YYYY-MM-DD")
    db = get_db()
    saved = db.execute("SELECT COALESCE(SUM(amount),0) FROM goal_contributions WHERE goal_id=?", (gid,)).fetchone()[0]
    if amount == 0 or saved + amount < 0:
        return err("enter a non-zero amount; you cannot withdraw more than you have saved")
    db.execute("INSERT INTO goal_contributions(goal_id,user_id,amount,date,note) VALUES(?,?,?,?,?)",
               (gid, session["user_id"], amount, when, clean_description(d.get("note", ""))[:80] or None))
    db.commit()
    return jsonify(ok=True), 201


@bp.delete("/api/goals/<int:gid>")
@login_required
def delete_goal(gid):
    if not _own_goal(gid):
        return err("not found", 404)
    db = get_db()
    db.execute("DELETE FROM goal_contributions WHERE goal_id=?", (gid,))
    db.execute("DELETE FROM goals WHERE id=?", (gid,))
    db.commit()
    return jsonify(ok=True)

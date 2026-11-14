"""Shared helpers used by every blueprint."""
import functools
from datetime import date

from flask import jsonify, redirect, request, session

from .db import get_db
from .ml import categorizer, recurring


def err(msg, code=400, **extra):
    return jsonify(error=msg, **extra), code


def current_user():
    """Row for the signed-in user, or None (also None if the account was disabled)."""
    uid = session.get("user_id")
    if not uid:
        return None
    row = get_db().execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
    if not row or not row["is_active"]:
        session.pop("user_id", None)
        session.pop("username", None)
        return None
    return row


def _deny():
    if request.path.startswith("/api/"):
        return jsonify(error="authentication required"), 401
    return redirect("/login")


def login_required(view):
    @functools.wraps(view)
    def wrapped(*a, **kw):
        if current_user() is None:
            return _deny()
        return view(*a, **kw)
    return wrapped


def admin_required(view):
    @functools.wraps(view)
    def wrapped(*a, **kw):
        u = current_user()
        if u is None:
            return _deny()
        if u["role"] != "admin":
            if request.path.startswith("/api/"):
                return jsonify(error="admin access required"), 403
            return redirect("/dashboard")
        return view(*a, **kw)
    return wrapped


def user_transactions(uid):
    rows = get_db().execute(
        "SELECT id,date,description,amount,type,category,confirmed,source FROM transactions "
        "WHERE user_id=? ORDER BY date DESC, id DESC", (uid,)).fetchall()
    return [dict(r) for r in rows]


def user_budgets(uid):
    rows = get_db().execute("SELECT category,monthly_limit FROM budgets WHERE user_id=?", (uid,)).fetchall()
    return {r["category"]: r["monthly_limit"] for r in rows}


def model_for(uid):
    rows = get_db().execute(
        "SELECT description,category FROM transactions WHERE user_id=? AND confirmed=1 AND type='expense'",
        (uid,)).fetchall()
    return categorizer.build_model([(r["description"], r["category"]) for r in rows])


def insert_rows(uid, rows, source="manual", import_id=None):
    """Insert parsed rows, auto-categorising expenses that have no category."""
    pending = [r for r in rows if r["type"] == "expense" and not r.get("category")]
    if pending:
        cats = categorizer.predict(model_for(uid), [r["description"] for r in pending])
        for r, c in zip(pending, cats):
            r["category"] = c
    db = get_db()
    for r in rows:
        cat = r.get("category") if r["type"] == "expense" else "Income"
        if r["type"] == "expense" and cat not in categorizer.CATEGORIES:
            cat = "Other"
        db.execute(
            "INSERT INTO transactions(user_id,date,description,amount,type,category,confirmed,source,import_id) "
            "VALUES(?,?,?,?,?,?,0,?,?)",
            (uid, r["date"], r["description"], r["amount"], r["type"], cat, source, import_id))
    db.commit()


def run_autopay(uid, today=None):
    """Record every autopay occurrence that has come due (catches up after downtime)."""
    today = today or date.today()
    db = get_db()
    rules = db.execute("SELECT * FROM autopay WHERE user_id=? AND active=1 AND next_date<=?",
                       (uid, today.isoformat())).fetchall()
    created = 0
    for r in rules:
        dates, nxt = recurring.due_dates(r["next_date"], r["frequency"], r["anchor_day"], today)
        for d in dates:
            db.execute("INSERT INTO transactions(user_id,date,description,amount,type,category,confirmed,source) "
                       "VALUES(?,?,?,?,?,?,1,'autopay')",
                       (uid, d.isoformat(), r["description"], r["amount"], r["type"], r["category"]))
            created += 1
        db.execute("UPDATE autopay SET next_date=? WHERE id=?", (nxt.isoformat(), r["id"]))
    db.commit()
    return created

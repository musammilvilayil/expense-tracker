import functools
from datetime import date

from flask import Blueprint, jsonify, redirect, render_template, request, session
from werkzeug.security import check_password_hash, generate_password_hash

from .db import get_db
from .ml import analysis, categorizer, subscriptions
from .ml.preprocess import clean_description, parse_csv, parse_date

bp = Blueprint("main", __name__)


# ---------- helpers ----------
def login_required(view):
    @functools.wraps(view)
    def wrapped(*a, **kw):
        if "user_id" not in session:
            if request.path.startswith("/api/"):
                return jsonify(error="authentication required"), 401
            return redirect("/login")
        return view(*a, **kw)
    return wrapped


def err(msg, code=400):
    return jsonify(error=msg), code


def user_transactions(uid):
    rows = get_db().execute(
        "SELECT id,date,description,amount,type,category,confirmed FROM transactions "
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


def insert_rows(uid, rows):
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
            "INSERT INTO transactions(user_id,date,description,amount,type,category,confirmed) VALUES(?,?,?,?,?,?,0)",
            (uid, r["date"], r["description"], r["amount"], r["type"], cat))
    db.commit()


# ---------- pages & auth ----------
@bp.get("/")
@login_required
def index():
    return render_template("dashboard.html", username=session["username"],
                           categories=categorizer.CATEGORIES, today=date.today().isoformat())


@bp.get("/login")
def login_page():
    return render_template("login.html")


@bp.post("/api/register")
def register():
    d = request.get_json(silent=True) or {}
    u, p = (d.get("username") or "").strip(), d.get("password") or ""
    if len(u) < 3 or len(p) < 8:
        return err("username needs 3+ chars and password 8+ chars")
    db = get_db()
    if db.execute("SELECT 1 FROM users WHERE username=?", (u,)).fetchone():
        return err("username already taken", 409)
    cur = db.execute("INSERT INTO users(username,password_hash) VALUES(?,?)", (u, generate_password_hash(p)))
    db.commit()
    session.clear()
    session.update(user_id=cur.lastrowid, username=u)
    return jsonify(ok=True), 201


@bp.post("/api/login")
def login():
    d = request.get_json(silent=True) or {}
    row = get_db().execute("SELECT * FROM users WHERE username=?", ((d.get("username") or "").strip(),)).fetchone()
    if not row or not check_password_hash(row["password_hash"], d.get("password") or ""):
        return err("invalid credentials", 401)
    session.clear()
    session.update(user_id=row["id"], username=row["username"])
    return jsonify(ok=True)


@bp.post("/api/logout")
def logout():
    session.clear()
    return jsonify(ok=True)


# ---------- transactions ----------
@bp.get("/api/transactions")
@login_required
def list_transactions():
    return jsonify(user_transactions(session["user_id"]))


@bp.post("/api/transactions")
@login_required
def add_transaction():
    d = request.get_json(silent=True) or {}
    try:
        row = {
            "date": parse_date(d.get("date", "")),
            "description": clean_description(d.get("description", "")),
            "amount": abs(float(d.get("amount"))),
            "type": d.get("type", "expense"),
            "category": d.get("category") or None,
        }
    except (TypeError, ValueError) as e:
        return err(str(e))
    if not row["description"] or row["amount"] <= 0 or row["type"] not in ("income", "expense"):
        return err("description, positive amount and valid type are required")
    insert_rows(session["user_id"], [row])
    return jsonify(ok=True), 201


@bp.post("/api/import")
@login_required
def import_csv():
    f = request.files.get("file")
    if not f:
        return err("file is required")
    try:
        content = f.read().decode("utf-8-sig")
    except UnicodeDecodeError:
        return err("file must be UTF-8 text")
    rows, errors = parse_csv(content)
    insert_rows(session["user_id"], rows)
    return jsonify(imported=len(rows), errors=errors[:20])


@bp.patch("/api/transactions/<int:tid>")
@login_required
def update_category(tid):
    cat = (request.get_json(silent=True) or {}).get("category")
    if cat not in categorizer.CATEGORIES:
        return err("unknown category")
    db = get_db()
    cur = db.execute("UPDATE transactions SET category=?, confirmed=1 WHERE id=? AND user_id=? AND type='expense'",
                     (cat, tid, session["user_id"]))
    db.commit()
    return (jsonify(ok=True) if cur.rowcount else err("not found", 404))


@bp.delete("/api/transactions/<int:tid>")
@login_required
def delete_transaction(tid):
    db = get_db()
    cur = db.execute("DELETE FROM transactions WHERE id=? AND user_id=?", (tid, session["user_id"]))
    db.commit()
    return (jsonify(ok=True) if cur.rowcount else err("not found", 404))


# ---------- budgets ----------
@bp.get("/api/budgets")
@login_required
def get_budgets():
    month = request.args.get("month") or date.today().strftime("%Y-%m")
    uid = session["user_id"]
    return jsonify(analysis.budget_status(user_transactions(uid), user_budgets(uid), month))


@bp.put("/api/budgets")
@login_required
def set_budget():
    d = request.get_json(silent=True) or {}
    try:
        limit = float(d.get("monthly_limit"))
    except (TypeError, ValueError):
        return err("monthly_limit must be a number")
    if d.get("category") not in categorizer.CATEGORIES or limit < 0:
        return err("valid category and non-negative limit required")
    db = get_db()
    if limit == 0:
        db.execute("DELETE FROM budgets WHERE user_id=? AND category=?", (session["user_id"], d["category"]))
    else:
        db.execute("INSERT INTO budgets VALUES(?,?,?) ON CONFLICT(user_id,category) DO UPDATE SET monthly_limit=excluded.monthly_limit",
                   (session["user_id"], d["category"], limit))
    db.commit()
    return jsonify(ok=True)


# ---------- insights ----------
@bp.get("/api/insights")
@login_required
def insights():
    uid = session["user_id"]
    month = request.args.get("month") or date.today().strftime("%Y-%m")
    txs = user_transactions(uid)
    budgets = user_budgets(uid)
    subs = subscriptions.detect(txs)
    return jsonify({
        "month": month,
        "summary": analysis.summarize(txs, month),
        "yearly": analysis.summarize(txs, month[:4]),
        "subscriptions": subs,
        "renewals_due": subscriptions.upcoming(subs),
        "anomalies": analysis.find_anomalies(txs),
        "budgets": analysis.budget_status(txs, budgets, month),
        "recommendations": analysis.recommendations(txs, subs, budgets, month),
    })

import re
from datetime import date, datetime

from flask import Blueprint, jsonify, redirect, render_template, request, session

from .db import get_db
from .helpers import (current_user, err, insert_rows, login_required, model_for, run_autopay,
                      user_budgets, user_transactions)
from .ml import analysis, categorizer, forecast, recurring, subscriptions
from .ml.preprocess import clean_description, parse_date

bp = Blueprint("main", __name__)


# ---------- pages & auth ----------
@bp.get("/")
def landing():
    return render_template("landing.html")


@bp.get("/features")
def features():
    return render_template("features.html")


@bp.get("/how-it-works")
def how_it_works():
    return render_template("how.html")


@bp.get("/about")
def about():
    return render_template("about.html")


@bp.get("/privacy")
def privacy():
    return render_template("privacy.html")


FAQS = [
    ("Is my data safe?", "Passwords are stored as salted hashes and each account only sees its own data. This is a student project, so avoid entering real data on a deployment without HTTPS."),
    ("Does it connect to my bank?", "No. You add transactions by hand or import a CSV. Bank integrations are future scope."),
    ("How does automatic categorization work?", "A machine-learning model (TF-IDF with logistic regression) predicts a category from the description. When you correct one, the model learns from it."),
    ("Why was a subscription not detected?", "A charge must repeat at least twice at a regular interval (weekly, monthly, quarterly or yearly) with a similar amount."),
    ("Does autopay really pay my bills?", "No. Autopay rules only record transactions in the tracker on their due dates. No money moves."),
    ("What CSV format should I use?", "Columns date, description and amount, with an optional type column (income or expense). Without type, negative amounts are expenses."),
    ("What counts as unusual spending?", "An expense far above the typical amount for its category. At least 5 expenses in that category are needed first."),
    ("How does the forecast work?", "It uses your completed monthly totals. Three simple models (recent average, weighted average and a damped trend) are tested on your own history, the most accurate one is used, and its past error gives the likely range. More months of data means a better forecast."),
    ("Is this financial advice?", "No. Tips are automated guidance based on your own numbers."),
    ("Can I delete my data?", "You can delete transactions and autopay rules. Account deletion and data export are planned."),
]


@bp.get("/faq")
def faq():
    return render_template("faq.html", faqs=FAQS)


@bp.route("/contact", methods=["GET", "POST"])
def contact():
    ctx = {"errors": [], "form": {}, "sent": False}
    if request.method == "POST":
        f = {k: (request.form.get(k) or "").strip() for k in ("name", "email", "subject", "message")}
        ctx["form"] = f
        if request.form.get("website"):  # honeypot: bots fill hidden field
            ctx.update(sent=True, form={})
            return render_template("contact.html", **ctx)
        if not (1 <= len(f["name"]) <= 80):
            ctx["errors"].append("Please enter your name (max 80 characters).")
        if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", f["email"]) or len(f["email"]) > 120:
            ctx["errors"].append("Please enter a valid email address.")
        if not (1 <= len(f["subject"]) <= 120):
            ctx["errors"].append("Please enter a subject (max 120 characters).")
        if not (10 <= len(f["message"]) <= 2000):
            ctx["errors"].append("Message must be 10 to 2000 characters.")
        if not ctx["errors"]:
            db = get_db()
            db.execute("INSERT INTO contact_messages(name,email,subject,message) VALUES(?,?,?,?)",
                       (f["name"], f["email"], f["subject"], f["message"]))
            db.commit()
            ctx.update(sent=True, form={})
        return render_template("contact.html", **ctx), (400 if ctx["errors"] else 200)
    return render_template("contact.html", **ctx)


@bp.get("/dashboard")
@login_required
def index():
    u = current_user()
    return render_template("dashboard.html", username=u["username"], is_admin=u["role"] == "admin",
                           categories=categorizer.CATEGORIES, today=date.today().isoformat())


# ---------- transactions ----------
@bp.get("/api/transactions")
@login_required
def list_transactions():
    run_autopay(session["user_id"])
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
    run_autopay(uid)
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


# ---------- autopay ----------
@bp.get("/api/autopay")
@login_required
def list_autopay():
    run_autopay(session["user_id"])
    rows = get_db().execute("SELECT id,description,amount,type,category,frequency,next_date,active "
                            "FROM autopay WHERE user_id=? ORDER BY next_date", (session["user_id"],)).fetchall()
    return jsonify([dict(r) for r in rows])


@bp.post("/api/autopay")
@login_required
def add_autopay():
    d = request.get_json(silent=True) or {}
    try:
        start = parse_date(d.get("start_date", ""))
        amount = abs(float(d.get("amount")))
    except (TypeError, ValueError) as e:
        return err(str(e))
    desc = clean_description(d.get("description", ""))
    ttype, freq = d.get("type", "expense"), d.get("frequency")
    if not desc or amount <= 0 or ttype not in ("income", "expense") or freq not in recurring.FREQUENCIES:
        return err("description, positive amount, type and frequency (weekly/monthly/quarterly/yearly) required")
    cat = None
    if ttype == "expense":
        cat = d.get("category")
        if cat not in categorizer.CATEGORIES:
            cat = categorizer.predict(model_for(session["user_id"]), [desc])[0]
    else:
        cat = "Income"
    anchor = datetime.strptime(start, "%Y-%m-%d").day
    db = get_db()
    db.execute("INSERT INTO autopay(user_id,description,amount,type,category,frequency,anchor_day,next_date) "
               "VALUES(?,?,?,?,?,?,?,?)", (session["user_id"], desc, amount, ttype, cat, freq, anchor, start))
    db.commit()
    run_autopay(session["user_id"])
    return jsonify(ok=True), 201


@bp.patch("/api/autopay/<int:aid>")
@login_required
def toggle_autopay(aid):
    active = 1 if (request.get_json(silent=True) or {}).get("active") else 0
    db = get_db()
    cur = db.execute("UPDATE autopay SET active=? WHERE id=? AND user_id=?", (active, aid, session["user_id"]))
    db.commit()
    return jsonify(ok=True) if cur.rowcount else err("not found", 404)


@bp.delete("/api/autopay/<int:aid>")
@login_required
def delete_autopay(aid):
    db = get_db()
    cur = db.execute("DELETE FROM autopay WHERE id=? AND user_id=?", (aid, session["user_id"]))
    db.commit()
    return jsonify(ok=True) if cur.rowcount else err("not found", 404)


# ---------- forecast ----------
@bp.get("/api/forecast")
@login_required
def get_forecast():
    uid = session["user_id"]
    run_autopay(uid)
    try:
        horizon = min(max(int(request.args.get("horizon", 3)), 1), 6)
    except ValueError:
        return err("horizon must be a number")
    txs = user_transactions(uid)
    rules = [dict(r) for r in get_db().execute(
        "SELECT description,amount,type,frequency,anchor_day,next_date,active FROM autopay WHERE user_id=?",
        (uid,)).fetchall()]
    return jsonify(forecast.build(txs, user_budgets(uid), rules, subscriptions.detect(txs), horizon=horizon))

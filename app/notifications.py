"""Reminders: in-app notifications plus an optional email digest.

Notifications are generated lazily and idempotently (UNIQUE per user+key), so
opening the dashboard many times never repeats one. `send_all` emails the
un-emailed ones and is meant to run daily from cron / Task Scheduler:
    python manage.py send-reminders
"""
from datetime import date, datetime, timedelta

from flask import Blueprint, jsonify, request, session

from . import mailer
from .db import get_db
from .goals import all_goals
from .helpers import err, login_required, run_autopay, user_budgets, user_transactions
from .ml import analysis, subscriptions
from .ml.preprocess import normalize_merchant

bp = Blueprint("notifications", __name__)
LEAD_DAYS = 7
GOAL_DAYS = 14
EMAIL_MAX_AGE_DAYS = 3


def _when(days):
    return "today" if days == 0 else "tomorrow" if days == 1 else f"in {days} days"


def _add(db, uid, key, kind, message, due=None):
    cur = db.execute("INSERT OR IGNORE INTO notifications(user_id,key,kind,message,due_date) VALUES(?,?,?,?,?)",
                     (uid, key, kind, message, due))
    return cur.rowcount


def generate(uid, today=None):
    """Create any reminders that are now due. Returns how many were new."""
    today = today or date.today()
    db, made = get_db(), 0
    run_autopay(uid, today)
    txs = user_transactions(uid)

    covered = set()
    for r in db.execute("SELECT id,description,amount,type,frequency,next_date FROM autopay WHERE user_id=? AND active=1", (uid,)):
        covered.add(normalize_merchant(r["description"]))
        days = (date.fromisoformat(r["next_date"]) - today).days
        if 0 <= days <= LEAD_DAYS:
            verb = "will be recorded" if r["type"] == "income" else "is due"
            made += _add(db, uid, f"autopay:{r['id']}:{r['next_date']}", "autopay",
                         f"Autopay: {r['description']} ({r['amount']:,.2f}) {verb} {_when(days)}.", r["next_date"])

    for s in subscriptions.detect(txs):
        if normalize_merchant(s["name"]) in covered:
            continue
        days = (date.fromisoformat(s["next_renewal"]) - today).days
        if 0 <= days <= LEAD_DAYS:
            made += _add(db, uid, f"renewal:{normalize_merchant(s['name'])}:{s['next_renewal']}", "renewal",
                         f"Subscription renewal: {s['name']} ({s['amount']:,.2f}) renews {_when(days)}.", s["next_renewal"])

    month = today.strftime("%Y-%m")
    for b in analysis.budget_status(txs, user_budgets(uid), month):
        if b["status"] in ("warning", "over"):
            text = (f"You are over your {b['category']} budget ({b['spent']:,.2f} of {b['limit']:,.2f})." if b["status"] == "over"
                    else f"You have used {b['percent']:.0f}% of your {b['category']} budget.")
            made += _add(db, uid, f"budget:{b['category']}:{month}:{b['status']}", "budget", text)

    for g in all_goals(uid, today):
        if g["target_date"] and g["status"] != "achieved":
            days = (date.fromisoformat(g["target_date"]) - today).days
            if 0 <= days <= GOAL_DAYS:
                made += _add(db, uid, f"goal:{g['id']}:{g['target_date']}", "goal",
                             f"Goal '{g['name']}' is due {_when(days)}: {g['saved']:,.2f} of {g['target_amount']:,.2f} saved.", g["target_date"])

    cutoff = (today - timedelta(days=7)).isoformat()
    for a in analysis.find_anomalies(txs):
        if a["date"] >= cutoff:
            made += _add(db, uid, f"anomaly:{a['id']}", "anomaly",
                         f"Unusual {a['category']} charge: {a['description']} ({a['amount']:,.2f}) vs typical {a['typical']:,.2f}.", a["date"])

    db.execute("DELETE FROM notifications WHERE user_id=? AND is_read=1 AND created_at < datetime('now','-90 days')", (uid,))
    db.commit()
    return made


def send_all(app, today=None):
    """Email a digest of fresh, un-emailed reminders to every opted-in user. Returns number of emails."""
    sent = 0
    with app.app_context():
        db = get_db()
        for u in db.execute("SELECT * FROM users WHERE is_active=1 AND email IS NOT NULL AND notify_email=1").fetchall():
            generate(u["id"], today)
            rows = db.execute("SELECT id,message FROM notifications WHERE user_id=? AND emailed=0 AND created_at >= datetime('now', ?) ORDER BY id",
                              (u["id"], f"-{EMAIL_MAX_AGE_DAYS} days")).fetchall()
            if not rows:
                continue
            body = f"Hi {u['username']},\n\nHere are your reminders:\n\n" + "\n".join(f"- {r['message']}" for r in rows) + \
                   "\n\nYou can turn these emails off in Settings."
            mailer.send_mail(u["email"], f"{len(rows)} finance reminder{'s' if len(rows) != 1 else ''}", body)
            db.executemany("UPDATE notifications SET emailed=1 WHERE id=?", [(r["id"],) for r in rows])
            db.commit()
            sent += 1
    return sent


@bp.get("/api/notifications")
@login_required
def list_notifications():
    uid, db = session["user_id"], get_db()
    generate(uid)
    rows = db.execute("SELECT id,kind,message,due_date,created_at,is_read FROM notifications WHERE user_id=? "
                      "ORDER BY is_read, id DESC LIMIT 30", (uid,)).fetchall()
    unread = db.execute("SELECT COUNT(*) FROM notifications WHERE user_id=? AND is_read=0", (uid,)).fetchone()[0]
    return jsonify(unread=unread, items=[dict(r) for r in rows])


@bp.post("/api/notifications/read")
@login_required
def mark_read():
    d, uid, db = request.get_json(silent=True) or {}, session["user_id"], get_db()
    ids = d.get("ids")
    if ids is None:
        db.execute("UPDATE notifications SET is_read=1 WHERE user_id=?", (uid,))
    elif isinstance(ids, list) and all(isinstance(i, int) for i in ids):
        db.executemany("UPDATE notifications SET is_read=1 WHERE user_id=? AND id=?", [(uid, i) for i in ids])
    else:
        return err("ids must be a list of numbers")
    db.commit()
    return jsonify(ok=True)

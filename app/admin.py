"""Admin panel. Admins manage accounts and support messages.

Privacy rule: nothing here returns anyone's transactions, budgets, goals or
other financial content. Users appear only with counts and account metadata.
"""
import json
import os

from flask import Blueprint, jsonify, render_template, request, session

from .account import issue_reset
from .db import get_db
from .helpers import admin_required, current_user, err

bp = Blueprint("admin", __name__)


def audit(db, action, target=""):
    db.execute("INSERT INTO audit_log(admin_id, action, target) VALUES(?,?,?)", (session["user_id"], action, str(target)[:200]))


@bp.get("/admin")
@admin_required
def admin_page():
    u = current_user()
    return render_template("admin.html", username=u["username"], is_admin=True)


@bp.get("/api/admin/stats")
@admin_required
def stats():
    db = get_db()
    one = lambda q: db.execute(q).fetchone()[0]
    return jsonify(users=one("SELECT COUNT(*) FROM users"), active_users=one("SELECT COUNT(*) FROM users WHERE is_active=1"),
                   admins=one("SELECT COUNT(*) FROM users WHERE role='admin'"), transactions=one("SELECT COUNT(*) FROM transactions"),
                   imports=one("SELECT COUNT(*) FROM imports"), open_messages=one("SELECT COUNT(*) FROM contact_messages WHERE resolved=0"))


@bp.get("/api/admin/users")
@admin_required
def users():
    rows = get_db().execute(
        "SELECT u.id,u.username,u.email,u.role,u.is_active,u.created_at,"
        "(SELECT COUNT(*) FROM transactions t WHERE t.user_id=u.id) AS transaction_count "
        "FROM users u ORDER BY u.id").fetchall()
    return jsonify([dict(r) for r in rows])


@bp.patch("/api/admin/users/<int:uid>")
@admin_required
def update_user(uid):
    d, db = request.get_json(silent=True) or {}, get_db()
    target = db.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
    if not target:
        return err("not found", 404)
    if uid == session["user_id"]:
        return err("you cannot change your own role or status", 409)
    if "is_active" in d:
        active = 1 if d["is_active"] else 0
        db.execute("UPDATE users SET is_active=? WHERE id=?", (active, uid))
        audit(db, "enable_user" if active else "disable_user", target["username"])
    if "role" in d:
        if d["role"] not in ("user", "admin"):
            return err("role must be user or admin")
        db.execute("UPDATE users SET role=? WHERE id=?", (d["role"], uid))
        audit(db, "promote_user" if d["role"] == "admin" else "demote_user", target["username"])
    db.commit()
    return jsonify(ok=True)


@bp.post("/api/admin/users/<int:uid>/reset-password")
@admin_required
def send_reset(uid):
    db = get_db()
    target = db.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
    if not target:
        return err("not found", 404)
    if not target["email"]:
        return err("this user has no email address on file", 409)
    issue_reset(db, target)  # the link goes to the user's inbox; admins never see it
    audit(db, "send_password_reset", target["username"])
    db.commit()
    return jsonify(ok=True)


@bp.get("/api/admin/messages")
@admin_required
def messages():
    rows = get_db().execute("SELECT id,name,email,subject,message,created_at,resolved FROM contact_messages ORDER BY resolved, id DESC LIMIT 200").fetchall()
    return jsonify([dict(r) for r in rows])


@bp.patch("/api/admin/messages/<int:mid>")
@admin_required
def resolve_message(mid):
    db = get_db()
    cur = db.execute("UPDATE contact_messages SET resolved=? WHERE id=?", (1 if (request.get_json(silent=True) or {}).get("resolved", True) else 0, mid))
    if not cur.rowcount:
        return err("not found", 404)
    audit(db, "update_message", mid)
    db.commit()
    return jsonify(ok=True)


@bp.delete("/api/admin/messages/<int:mid>")
@admin_required
def delete_message(mid):
    db = get_db()
    if not db.execute("DELETE FROM contact_messages WHERE id=?", (mid,)).rowcount:
        return err("not found", 404)
    audit(db, "delete_message", mid)
    db.commit()
    return jsonify(ok=True)


@bp.get("/api/admin/audit")
@admin_required
def audit_log():
    rows = get_db().execute(
        "SELECT a.id,a.action,a.target,a.created_at,u.username AS admin FROM audit_log a LEFT JOIN users u ON u.id=a.admin_id "
        "ORDER BY a.id DESC LIMIT 50").fetchall()
    return jsonify([dict(r) for r in rows])


@bp.get("/api/admin/model")
@admin_required
def model_metrics():
    path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "docs", "categorizer_metrics.json")
    if not os.path.exists(path):
        return jsonify(available=False)
    with open(path, encoding="utf-8") as f:
        return jsonify(available=True, metrics=json.load(f))

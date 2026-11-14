"""Authentication, password reset, settings, data export and account deletion."""
import hashlib
import json
import os
import re
import secrets
import time
from datetime import datetime, timezone

from flask import Blueprint, Response, current_app, jsonify, redirect, render_template, request, session
from werkzeug.security import check_password_hash, generate_password_hash

from . import mailer, security
from .db import get_db
from .helpers import current_user, err, login_required

bp = Blueprint("account", __name__)
EMAIL_RE = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")
RESET_TTL = 60 * 60
_DUMMY_HASH = generate_password_hash("not-a-real-password")


def now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def valid_password(pw, username=""):
    if len(pw) < 8:
        return "password needs at least 8 characters"
    if len(pw) > 200:
        return "password is too long"
    if username and pw.lower() == username.lower():
        return "password must not equal your username"
    return None


def admin_usernames():
    raw = current_app.config.get("ADMIN_USERNAMES") or os.environ.get("ADMIN_USERNAMES") or ""
    return {u.strip().lower() for u in raw.split(",") if u.strip()}


def _promote_if_listed(db, username):
    if username.lower() in admin_usernames():
        db.execute("UPDATE users SET role='admin' WHERE lower(username)=?", (username.lower(),))
        db.commit()


def _login(row):
    session.clear()
    session.update(user_id=row["id"], username=row["username"])
    security.csrf_token()


def issue_reset(db, user):
    """Create a single-use reset token and email the link. Returns the link."""
    token = secrets.token_urlsafe(32)
    db.execute("UPDATE password_resets SET used=1 WHERE user_id=? AND used=0", (user["id"],))
    db.execute("INSERT INTO password_resets(user_id, token_hash, expires_at) VALUES(?,?,?)",
               (user["id"], hashlib.sha256(token.encode()).hexdigest(), time.time() + RESET_TTL))
    db.commit()
    base = (current_app.config.get("BASE_URL") or os.environ.get("BASE_URL") or request.host_url).rstrip("/")
    link = f"{base}/reset/{token}"
    mailer.send_mail(user["email"], "Reset your password",
                     f"Hi {user['username']},\n\nUse this link to choose a new password (valid for 1 hour):\n{link}\n\n"
                     "If you did not request this, you can ignore this email.")
    return link


# ---------- pages ----------
@bp.get("/login")
def login_page():
    if current_user() is not None:
        return redirect("/dashboard")
    return render_template("login.html")


@bp.get("/forgot")
def forgot_page():
    return render_template("forgot.html")


@bp.get("/reset/<token>")
def reset_page(token):
    return render_template("reset.html", token=token)


@bp.get("/settings")
@login_required
def settings_page():
    u = current_user()
    return render_template("settings.html", username=u["username"], is_admin=u["role"] == "admin")


# ---------- register / login / logout ----------
@bp.post("/api/register")
def register():
    d = request.get_json(silent=True) or {}
    u, p, email = (d.get("username") or "").strip(), d.get("password") or "", (d.get("email") or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9_.-]{3,40}", u):
        return err("username must be 3-40 letters, numbers, dot, dash or underscore")
    if (msg := valid_password(p, u)):
        return err(msg)
    if email and (not EMAIL_RE.fullmatch(email) or len(email) > 120):
        return err("please enter a valid email address")
    db = get_db()
    if db.execute("SELECT 1 FROM users WHERE lower(username)=?", (u.lower(),)).fetchone():
        return err("username already taken", 409)
    if email and db.execute("SELECT 1 FROM users WHERE lower(email)=?", (email.lower(),)).fetchone():
        return err("that email is already registered", 409)
    cur = db.execute("INSERT INTO users(username,password_hash,email,created_at) VALUES(?,?,?,?)",
                     (u, generate_password_hash(p), email or None, now_iso()))
    db.commit()
    _promote_if_listed(db, u)
    _login(db.execute("SELECT * FROM users WHERE id=?", (cur.lastrowid,)).fetchone())
    return jsonify(ok=True), 201


@bp.post("/api/login")
def login():
    d = request.get_json(silent=True) or {}
    username, password = (d.get("username") or "").strip(), d.get("password") or ""
    db = get_db()
    if security.too_many_attempts(db, username):
        return err("too many failed attempts. Try again in 15 minutes.", 429)
    row = db.execute("SELECT * FROM users WHERE lower(username)=?", (username.lower(),)).fetchone()
    ok = check_password_hash(row["password_hash"] if row else _DUMMY_HASH, password)
    if not row or not ok:
        security.record_failure(db, username)
        return err("invalid credentials", 401)
    if not row["is_active"]:
        return err("this account has been disabled", 403)
    security.clear_failures(db, username)
    _promote_if_listed(db, row["username"])
    _login(row)
    return jsonify(ok=True)


@bp.post("/api/logout")
def logout():
    session.clear()
    return jsonify(ok=True)


# ---------- password reset ----------
@bp.post("/api/forgot")
def forgot():
    email = ((request.get_json(silent=True) or {}).get("email") or "").strip().lower()
    db = get_db()
    key = f"forgot|{request.remote_addr}"
    if security.too_many_attempts(db, key):
        return err("too many requests. Try again later.", 429)
    security.record_failure(db, key)  # counts every request from this address
    if EMAIL_RE.fullmatch(email):
        user = db.execute("SELECT * FROM users WHERE lower(email)=? AND is_active=1", (email,)).fetchone()
        if user:
            issue_reset(db, user)
    # identical response whether or not the address exists
    return jsonify(ok=True, message="If that email is registered, a reset link has been sent.")


@bp.post("/api/reset")
def reset():
    d = request.get_json(silent=True) or {}
    token, pw = d.get("token") or "", d.get("password") or ""
    db = get_db()
    row = db.execute("SELECT * FROM password_resets WHERE token_hash=?",
                     (hashlib.sha256(token.encode()).hexdigest(),)).fetchone()
    if not row or row["used"] or row["expires_at"] < time.time():
        return err("this reset link is invalid or has expired", 400)
    user = db.execute("SELECT * FROM users WHERE id=?", (row["user_id"],)).fetchone()
    if (msg := valid_password(pw, user["username"])):
        return err(msg)
    db.execute("UPDATE users SET password_hash=? WHERE id=?", (generate_password_hash(pw), user["id"]))
    db.execute("UPDATE password_resets SET used=1 WHERE user_id=?", (user["id"],))
    db.execute("DELETE FROM login_attempts WHERE key LIKE ?", (f"%|{user['username'].lower()}",))
    db.commit()
    return jsonify(ok=True)


# ---------- account settings ----------
@bp.get("/api/account")
@login_required
def get_account():
    u = current_user()
    return jsonify(username=u["username"], email=u["email"], notify_email=bool(u["notify_email"]),
                   role=u["role"], created_at=u["created_at"])


@bp.patch("/api/account")
@login_required
def update_account():
    u, d = current_user(), request.get_json(silent=True) or {}
    db = get_db()
    if "email" in d:
        email = (d["email"] or "").strip()
        if email and (not EMAIL_RE.fullmatch(email) or len(email) > 120):
            return err("please enter a valid email address")
        if email and db.execute("SELECT 1 FROM users WHERE lower(email)=? AND id!=?", (email.lower(), u["id"])).fetchone():
            return err("that email is already registered", 409)
        db.execute("UPDATE users SET email=? WHERE id=?", (email or None, u["id"]))
    if "notify_email" in d:
        db.execute("UPDATE users SET notify_email=? WHERE id=?", (1 if d["notify_email"] else 0, u["id"]))
    db.commit()
    return jsonify(ok=True)


@bp.post("/api/account/password")
@login_required
def change_password():
    u, d = current_user(), request.get_json(silent=True) or {}
    if not check_password_hash(u["password_hash"], d.get("current") or ""):
        return err("current password is incorrect", 403)
    if (msg := valid_password(d.get("new") or "", u["username"])):
        return err(msg)
    db = get_db()
    db.execute("UPDATE users SET password_hash=? WHERE id=?", (generate_password_hash(d["new"]), u["id"]))
    db.commit()
    return jsonify(ok=True)


def _rows(db, sql, uid):
    return [dict(r) for r in db.execute(sql, (uid,)).fetchall()]


@bp.get("/api/account/export")
@login_required
def export_account():
    u, db = current_user(), get_db()
    data = {
        "exported_at": now_iso(),
        "profile": {"username": u["username"], "email": u["email"], "created_at": u["created_at"]},
        "transactions": _rows(db, "SELECT date,description,amount,type,category,source FROM transactions WHERE user_id=? ORDER BY date", u["id"]),
        "budgets": _rows(db, "SELECT category,monthly_limit FROM budgets WHERE user_id=?", u["id"]),
        "autopay": _rows(db, "SELECT description,amount,type,category,frequency,next_date,active FROM autopay WHERE user_id=?", u["id"]),
        "goals": _rows(db, "SELECT id,name,target_amount,target_date,created_at FROM goals WHERE user_id=?", u["id"]),
        "goal_contributions": _rows(db, "SELECT goal_id,amount,date,note FROM goal_contributions WHERE user_id=?", u["id"]),
        "imports": _rows(db, "SELECT filename,kind,rows_total,rows_new,rows_duplicate,created_at FROM imports WHERE user_id=?", u["id"]),
        "notifications": _rows(db, "SELECT kind,message,due_date,created_at FROM notifications WHERE user_id=?", u["id"]),
    }
    return Response(json.dumps(data, indent=2), mimetype="application/json",
                    headers={"Content-Disposition": "attachment; filename=my-finance-data.json"})


@bp.post("/api/account/delete")
@login_required
def delete_account():
    u, d = current_user(), request.get_json(silent=True) or {}
    if not check_password_hash(u["password_hash"], d.get("password") or ""):
        return err("password is incorrect", 403)
    db = get_db()
    if u["role"] == "admin" and db.execute("SELECT COUNT(*) FROM users WHERE role='admin' AND is_active=1").fetchone()[0] <= 1:
        return err("you are the only administrator. Make another admin first.", 409)
    uid = u["id"]
    for table in ("goal_contributions", "goals", "notifications", "password_resets", "imports",
                  "autopay", "budgets", "transactions"):
        db.execute(f"DELETE FROM {table} WHERE user_id=?", (uid,))
    db.execute("DELETE FROM users WHERE id=?", (uid,))
    db.commit()
    session.clear()
    return jsonify(ok=True)

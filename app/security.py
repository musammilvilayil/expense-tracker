"""CSRF protection, security headers and login rate limiting."""
import hmac
import secrets
import time

from flask import jsonify, render_template, request, session

SAFE = {"GET", "HEAD", "OPTIONS"}
MAX_FAILS, WINDOW = 5, 15 * 60


def csrf_token():
    if "csrf" not in session:
        session["csrf"] = secrets.token_urlsafe(32)
    return session["csrf"]


def check_csrf():
    if request.method in SAFE:
        return None
    sent = request.headers.get("X-CSRF-Token") or request.form.get("csrf_token") or ""
    expected = session.get("csrf", "")
    if not expected or not hmac.compare_digest(sent, expected):
        if request.path.startswith("/api/"):
            return jsonify(error="invalid or missing CSRF token; reload the page"), 403
        return render_template("notfound.html", message="Your session expired. Reload the page and try again."), 403
    return None


def add_headers(resp):
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    resp.headers.setdefault("X-Frame-Options", "DENY")
    resp.headers.setdefault("Referrer-Policy", "same-origin")
    if request.path.startswith("/api/") or request.path in ("/dashboard", "/settings", "/admin"):
        resp.headers.setdefault("Cache-Control", "no-store")
    return resp


# ---- login rate limiting (stored in the database so it survives restarts) ----
def _key(username):
    return f"{request.remote_addr}|{(username or '').lower()}"


def too_many_attempts(db, username):
    cutoff = time.time() - WINDOW
    n = db.execute("SELECT COUNT(*) FROM login_attempts WHERE key=? AND ts>?", (_key(username), cutoff)).fetchone()[0]
    return n >= MAX_FAILS


def record_failure(db, username):
    db.execute("INSERT INTO login_attempts(key, ts) VALUES(?,?)", (_key(username), time.time()))
    db.execute("DELETE FROM login_attempts WHERE ts<?", (time.time() - WINDOW,))
    db.commit()


def clear_failures(db, username):
    db.execute("DELETE FROM login_attempts WHERE key=?", (_key(username),))
    db.commit()

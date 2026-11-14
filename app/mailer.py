"""Outgoing email. Uses SMTP when configured, otherwise records to an outbox.

Set SMTP_HOST (and optionally SMTP_PORT, SMTP_USER, SMTP_PASSWORD, MAIL_FROM)
in the environment to send real email. Without it, messages are appended to
instance/outbox.log so password-reset links can still be used in development.
"""
import logging
import os
import smtplib
import time
from email.message import EmailMessage

from flask import current_app

log = logging.getLogger(__name__)


def send_mail(to: str, subject: str, body: str) -> bool:
    app = current_app
    app.extensions.setdefault("outbox", []).append({"to": to, "subject": subject, "body": body})
    host = app.config.get("SMTP_HOST") or os.environ.get("SMTP_HOST")
    if not host:
        try:
            with open(os.path.join(app.instance_path, "outbox.log"), "a", encoding="utf-8") as f:
                f.write(f"--- {time.strftime('%Y-%m-%d %H:%M:%S')}\nTo: {to}\nSubject: {subject}\n\n{body}\n\n")
        except OSError:
            log.exception("could not write outbox")
        return False
    msg = EmailMessage()
    msg["From"] = app.config.get("MAIL_FROM") or os.environ.get("MAIL_FROM") or "no-reply@localhost"
    msg["To"], msg["Subject"] = to, subject
    msg.set_content(body)
    try:
        port = int(app.config.get("SMTP_PORT") or os.environ.get("SMTP_PORT") or 587)
        with smtplib.SMTP(host, port, timeout=15) as s:
            s.starttls()
            user = app.config.get("SMTP_USER") or os.environ.get("SMTP_USER")
            if user:
                s.login(user, app.config.get("SMTP_PASSWORD") or os.environ.get("SMTP_PASSWORD") or "")
            s.send_message(msg)
        return True
    except Exception:  # never break a request because mail failed
        log.exception("mail send failed")
        return False

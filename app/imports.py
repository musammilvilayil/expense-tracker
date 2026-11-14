"""Statement import: preview -> confirm, with duplicate detection, history and undo."""
import hashlib
import re
from datetime import date, datetime

from flask import Blueprint, jsonify, request, session

from .db import get_db
from .helpers import err, insert_rows, login_required
from .ml import dedupe, statement
from .ml.preprocess import clean_description, parse_csv

bp = Blueprint("imports", __name__)
MAX_ROWS = 5000


def _existing(uid, rows):
    if not rows:
        return []
    lo, hi = min(r["date"] for r in rows), max(r["date"] for r in rows)
    cur = get_db().execute("SELECT id,date,description,amount,type FROM transactions WHERE user_id=? AND date BETWEEN ? AND ?",
                           (uid, lo, hi))
    return [dict(r) for r in cur.fetchall()]


def _read_upload(f, password):
    name = f.filename or "upload"
    data = f.read()
    digest = hashlib.sha256(data).hexdigest()
    lower = name.lower()
    if data[:5] == b"%PDF-" or lower.endswith(".pdf"):
        rows, warnings = statement.parse_pages(statement.extract_pages(data, password))
        return "pdf", name, digest, rows, warnings
    if not lower.endswith((".csv", ".txt")):
        raise statement.StatementError("unsupported", "Upload a PDF bank statement or a CSV file.")
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = data.decode("cp1252", errors="replace")
    rows, errors = parse_csv(text)
    if not rows:
        raise statement.StatementError("no_transactions", "No valid rows found. Expected columns: date, description, amount[, type]."
                                       + (f" First problem: {errors[0]}" if errors else ""))
    return "csv", name, digest, rows, errors[:10]


@bp.post("/api/import/preview")
@login_required
def preview():
    f = request.files.get("file")
    if not f:
        return err("choose a file to import")
    uid = session["user_id"]
    try:
        kind, name, digest, rows, warnings = _read_upload(f, request.form.get("password") or None)
    except statement.StatementError as e:
        return err(e.message, 422, code=e.code)
    if len(rows) > MAX_ROWS:
        return err(f"too many rows ({len(rows)}). Split the file into smaller periods.", 422, code="too_large")
    matches = dedupe.find_duplicates(rows, _existing(uid, rows))
    out = []
    for i, (r, m) in enumerate(zip(rows, matches)):
        out.append({"i": i, "date": r["date"], "description": r["description"], "amount": r["amount"], "type": r["type"],
                    "confidence": r.get("confidence"), "duplicate": m is not None,
                    "matched": m["description"] if m else None})
    prev = get_db().execute("SELECT id,created_at FROM imports WHERE user_id=? AND file_hash=? ORDER BY id DESC LIMIT 1",
                            (uid, digest)).fetchone()
    dups = sum(1 for r in out if r["duplicate"])
    return jsonify(kind=kind, filename=name, file_hash=digest, rows=out, warnings=warnings,
                   counts={"total": len(out), "new": len(out) - dups, "duplicate": dups},
                   date_from=min(r["date"] for r in rows), date_to=max(r["date"] for r in rows),
                   already_imported=dict(prev) if prev else None)


def _clean_rows(raw):
    rows = []
    for n, r in enumerate(raw, 1):
        try:
            d = datetime.strptime(str(r.get("date", "")), "%Y-%m-%d").date().isoformat()
            amount = round(abs(float(r.get("amount"))), 2)
        except (TypeError, ValueError):
            raise ValueError(f"row {n}: invalid date or amount")
        desc = clean_description(str(r.get("description", "")))
        if not desc or amount <= 0 or r.get("type") not in ("income", "expense"):
            raise ValueError(f"row {n}: needs a description, positive amount and type income/expense")
        rows.append({"date": d, "description": desc, "amount": amount, "type": r["type"], "category": r.get("category") or None})
    return rows


@bp.post("/api/import/confirm")
@login_required
def confirm():
    d = request.get_json(silent=True) or {}
    raw = d.get("rows")
    if not isinstance(raw, list) or not raw:
        return err("no rows to import")
    if len(raw) > MAX_ROWS:
        return err("too many rows in one import", 422)
    try:
        rows = _clean_rows(raw)
    except ValueError as e:
        return err(str(e), 422)
    uid, db = session["user_id"], get_db()
    # Re-check duplicates now, so a double click or a parallel upload cannot add rows twice.
    matches = dedupe.find_duplicates(rows, _existing(uid, rows))
    fresh = [r for r, m in zip(rows, matches) if m is None]
    kind = d.get("kind") if d.get("kind") in ("pdf", "csv") else "csv"
    digest = re.sub(r"[^0-9a-f]", "", str(d.get("file_hash") or ""))[:64] or "n/a"
    cur = db.execute(
        "INSERT INTO imports(user_id,filename,file_hash,kind,rows_total,rows_new,rows_duplicate,date_from,date_to) VALUES(?,?,?,?,?,?,?,?,?)",
        (uid, str(d.get("filename") or "upload")[:120], digest, kind, len(rows), len(fresh), len(rows) - len(fresh),
         min(r["date"] for r in rows), max(r["date"] for r in rows)))
    db.commit()
    if fresh:
        insert_rows(uid, fresh, source=kind, import_id=cur.lastrowid)
    return jsonify(imported=len(fresh), skipped_duplicates=len(rows) - len(fresh), import_id=cur.lastrowid), 201


@bp.get("/api/imports")
@login_required
def history():
    rows = get_db().execute(
        "SELECT id,filename,kind,rows_total,rows_new,rows_duplicate,date_from,date_to,created_at FROM imports "
        "WHERE user_id=? ORDER BY id DESC LIMIT 20", (session["user_id"],)).fetchall()
    return jsonify([dict(r) for r in rows])


@bp.delete("/api/imports/<int:iid>")
@login_required
def undo(iid):
    uid, db = session["user_id"], get_db()
    if not db.execute("SELECT 1 FROM imports WHERE id=? AND user_id=?", (iid, uid)).fetchone():
        return err("not found", 404)
    n = db.execute("DELETE FROM transactions WHERE import_id=? AND user_id=?", (iid, uid)).rowcount
    db.execute("DELETE FROM imports WHERE id=? AND user_id=?", (iid, uid))
    db.commit()
    return jsonify(ok=True, removed=n)

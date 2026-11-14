from datetime import date, timedelta

import pytest

from app import create_app
from app.ml import analysis, categorizer, subscriptions
from app.ml.preprocess import parse_csv


def tx(d, desc, amt, typ="expense", cat="Other", i=0):
    return {"id": i, "date": d, "description": desc, "amount": amt, "type": typ, "category": cat}


def test_categorizer_known_merchants():
    m = categorizer.build_model()
    out = categorizer.predict(m, ["Netflix subscription 1299", "Uber ride 22", "Swiggy order #44", "Electricity bill"])
    assert out == ["Entertainment", "Transport", "Food", "Bills"]


def test_user_feedback_overrides():
    m = categorizer.build_model([("Zorblax Corp", "Education")])
    assert categorizer.predict(m, ["Zorblax Corp"]) == ["Education"]


def test_subscription_detection_monthly():
    txs = [tx(f"2026-0{i}-05", f"Netflix {i}", 199, i=i) for i in range(1, 5)]
    txs += [tx("2026-02-11", "Coffee", 5), tx("2026-03-02", "Coffee", 7)]
    subs = subscriptions.detect(txs)
    assert len(subs) == 1 and subs[0]["frequency"] == "monthly"
    assert subs[0]["next_renewal"] == "2026-05-05" or subs[0]["next_renewal"] == "2026-05-04"


def test_subscription_rejects_varying_amounts():
    txs = [tx("2026-01-05", "Shop", 10), tx("2026-02-05", "Shop", 80), tx("2026-03-05", "Shop", 25)]
    assert subscriptions.detect(txs) == []


def test_anomaly_detection():
    txs = [tx(f"2026-01-{d:02d}", "Lunch", 10 + d % 3, cat="Food", i=d) for d in range(1, 11)]
    txs.append(tx("2026-01-20", "Banquet", 400, cat="Food", i=99))
    an = analysis.find_anomalies(txs)
    assert [a["id"] for a in an] == [99]


def test_csv_parsing_keeps_repeated_lines_and_reports_errors():
    # identical lines in one file can be genuine purchases, so they are kept; overlap with saved data is ml/dedupe.py
    rows, errs = parse_csv("date,description,amount\n2026-01-01,Salary,5000\n2026-01-02,Uber,-12\n2026-01-02,Uber,-12\nbad,x,1\n")
    assert [r["type"] for r in rows] == ["income", "expense", "expense"] and len(errs) == 1


@pytest.fixture
def client(tmp_path):
    app = create_app({"TESTING": True, "DATABASE": str(tmp_path / "t.sqlite")})
    c = app.test_client()
    assert c.post("/api/register", json={"username": "alice", "password": "password123"}).status_code == 201
    return c


def test_requires_auth(tmp_path):
    c = create_app({"TESTING": True, "DATABASE": str(tmp_path / "x.sqlite")}).test_client()
    assert c.get("/api/transactions").status_code == 401


def test_end_to_end(client):
    month = date.today().strftime("%Y-%m")
    client.post("/api/transactions", json={"date": f"{month}-01", "description": "Salary", "amount": 3000, "type": "income"})
    client.post("/api/transactions", json={"date": f"{month}-02", "description": "Swiggy order", "amount": 40})
    client.put("/api/budgets", json={"category": "Food", "monthly_limit": 30})
    ins = client.get(f"/api/insights?month={month}").get_json()
    assert ins["summary"]["income"] == 3000 and ins["summary"]["by_category"] == {"Food": 40}
    assert ins["budgets"][0]["status"] == "over"
    tid = client.get("/api/transactions").get_json()[0]["id"]
    assert client.patch(f"/api/transactions/{tid}", json={"category": "Shopping"}).status_code in (200, 404)


def test_users_isolated(client, tmp_path):
    client.post("/api/transactions", json={"date": "2026-01-01", "description": "Rent", "amount": 500})
    tid = client.get("/api/transactions").get_json()[0]["id"]
    app = client.application
    bob = app.test_client()
    bob.post("/api/register", json={"username": "bobby", "password": "password123"})
    assert bob.get("/api/transactions").get_json() == []
    assert bob.delete(f"/api/transactions/{tid}").status_code == 404


def test_autopay_schedule_math():
    from app.ml.recurring import due_dates
    dates, nxt = due_dates("2026-01-31", "monthly", 31, date(2026, 4, 1))
    assert [d.isoformat() for d in dates] == ["2026-01-31", "2026-02-28", "2026-03-31"]
    assert nxt.isoformat() == "2026-04-30"


def test_autopay_creates_catches_up_and_pauses(client):
    start = (date.today() - timedelta(days=65)).isoformat()
    r = client.post("/api/autopay", json={"description": "Netflix", "amount": 199, "frequency": "monthly", "start_date": start})
    assert r.status_code == 201
    txs = client.get("/api/transactions").get_json()
    assert len(txs) >= 3 and all(t["description"] == "Netflix" for t in txs)
    assert client.get("/api/transactions").get_json() == txs  # idempotent, no duplicates
    rule = client.get("/api/autopay").get_json()[0]
    assert rule["next_date"] > date.today().isoformat()
    assert client.patch(f"/api/autopay/{rule['id']}", json={"active": False}).status_code == 200


def test_autopay_validation_and_isolation(client):
    assert client.post("/api/autopay", json={"description": "x", "amount": 5, "frequency": "daily", "start_date": "2026-01-01"}).status_code == 400
    client.post("/api/autopay", json={"description": "Gym", "amount": 50, "frequency": "monthly", "start_date": "2099-01-01"})
    aid = client.get("/api/autopay").get_json()[0]["id"]
    bob = client.application.test_client()
    bob.post("/api/register", json={"username": "bobby", "password": "password123"})
    assert bob.delete(f"/api/autopay/{aid}").status_code == 404


@pytest.mark.parametrize("path", ["/", "/features", "/how-it-works", "/about", "/privacy", "/login"])
def test_public_pages_open_without_login(tmp_path, path):
    c = create_app({"TESTING": True, "DATABASE": str(tmp_path / "p.sqlite")}).test_client()
    r = c.get(path)
    assert r.status_code == 200 and b"<title>" in r.data


def test_dashboard_requires_login_and_nav_changes(client, tmp_path):
    anon = create_app({"TESTING": True, "DATABASE": str(tmp_path / "q.sqlite")}).test_client()
    assert anon.get("/dashboard").status_code == 302
    assert b"Sign in" in anon.get("/").data
    assert client.get("/dashboard").status_code == 200
    assert b'href="/dashboard"' in client.get("/").data
    assert client.get("/login").status_code == 302


def test_faq_and_contact_pages(tmp_path):
    app = create_app({"TESTING": True, "DATABASE": str(tmp_path / "c.sqlite")})
    c = app.test_client()
    assert c.get("/faq").status_code == 200 and b"<details" in c.get("/faq").data
    assert c.get("/contact").status_code == 200
    bad = c.post("/contact", data={"name": "", "email": "nope", "subject": "", "message": "hi"})
    assert bad.status_code == 400 and b"valid email" in bad.data
    ok = c.post("/contact", data={"name": "Ann", "email": "ann@example.com", "subject": "Hi", "message": "Hello there, team"})
    assert ok.status_code == 200 and b"received" in ok.data
    spam = c.post("/contact", data={"name": "x", "email": "x@x.co", "subject": "s", "message": "spam spam spam", "website": "http://spam"})
    assert b"received" in spam.data
    with app.app_context():
        from app.db import get_db
        rows = get_db().execute("SELECT name FROM contact_messages").fetchall()
        assert [r["name"] for r in rows] == ["Ann"]


def test_404_pages(tmp_path):
    c = create_app({"TESTING": True, "DATABASE": str(tmp_path / "n.sqlite")}).test_client()
    r = c.get("/nope")
    assert r.status_code == 404 and b"wandered off" in r.data
    assert c.get("/api/nope").get_json() == {"error": "not found"}
    assert b"site.js" in c.get("/").data


# ---------- forecasting ----------
from app.ml import forecast as fc


def _spend(month, amount, cat="Food", d=10):
    return tx(f"{month}-{d:02d}", "Spend", amount, cat=cat)


def test_forecast_follows_linear_growth():
    p = fc.predict([100, 120, 140, 160, 180, 200])
    assert 190 <= p["pred"] <= 215 and p["low"] <= p["pred"] <= p["high"]


def test_forecast_flat_series_has_tight_range():
    p = fc.predict([500, 500, 500, 500, 500])
    assert p["pred"] == 500 and p["high"] - p["low"] <= 70  # 5% noise floor


def test_forecast_low_data_and_empty():
    assert fc.predict([])["pred"] == 0
    one = fc.predict([300])
    assert one["pred"] == 300 and one["high"] > one["low"]
    assert fc.confidence(2) == "low" and fc.confidence(4) == "medium" and fc.confidence(8) == "high"


def test_forecast_never_negative_and_horizon_widens():
    h = fc.predict_horizon([10, 200, 5, 180, 20, 90], 3)
    assert all(x["low"] >= 0 for x in h)
    assert (h[2]["high"] - h[2]["low"]) >= (h[0]["high"] - h[0]["low"])


def test_build_fills_gap_months_and_projects_current_month():
    today = date(2026, 11, 15)
    txs = [_spend("2026-08", 300), _spend("2026-10", 500), _spend("2026-11", 250, d=5),
           tx("2026-08-01", "Salary", 2000, "income", "Income"), tx("2026-10-01", "Salary", 2000, "income", "Income")]
    r = fc.build(txs, {"Food": 400}, [], [], today=today)
    assert r["history"]["months"] == ["2026-08", "2026-09", "2026-10"]
    assert r["history"]["expense"] == [300, 0, 500]          # empty September counted as 0
    assert r["current_month"]["spent_so_far"] == 250 and r["current_month"]["days_left"] == 15
    assert r["forecast"]["months"] == ["2026-12", "2027-01", "2027-02"]
    assert r["categories"][0]["category"] == "Food" and r["categories"][0]["budget_risk"] in ("over", "warning", "ok")
    assert r["insights"]


def test_build_with_only_current_month_data():
    today = date(2026, 11, 10)
    r = fc.build([_spend("2026-11", 100, d=3)], {}, [], [], today=today)
    assert r["confidence"] == "low" and r["forecast"]["expense"]
    assert fc.build([], {}, [], [], today=today)["insights"] == ["Add some transactions to unlock forecasts."]


def test_commitments_include_autopay_and_dedupe_subscriptions():
    today = date(2026, 11, 15)
    rules = [{"description": "Rent", "amount": 800, "type": "expense", "frequency": "monthly", "anchor_day": 20, "next_date": "2026-11-20", "active": 1},
             {"description": "Old", "amount": 5, "type": "expense", "frequency": "monthly", "anchor_day": 1, "next_date": "2026-11-20", "active": 0}]
    subs = [{"name": "Rent", "amount": 800, "next_renewal": "2026-11-20"}, {"name": "Netflix", "amount": 199, "next_renewal": "2026-11-25"}]
    items = fc.upcoming_commitments(rules, subs, today)
    assert [(i["name"], i["source"]) for i in items] == [("Rent", "autopay"), ("Netflix", "subscription")]


def test_forecast_endpoint(client):
    assert client.application.test_client().get("/api/forecast").status_code == 401
    for m, amt in [(8, 300), (9, 340), (10, 380)]:
        y = date.today().year if date.today().month > 10 else date.today().year - 1
        client.post("/api/transactions", json={"date": f"{y}-{m:02d}-10", "description": "Swiggy order", "amount": amt})
    r = client.get("/api/forecast?horizon=2")
    assert r.status_code == 200
    body = r.get_json()
    assert len(body["forecast"]["months"]) == 2 and "insights" in body and "categories" in body
    assert client.get("/api/forecast?horizon=abc").status_code == 400


# ---------- foundation & accounts ----------
import sqlite3

from app import create_app as _mk


def mk(tmp_path, name="a.sqlite", **cfg):
    return _mk({"TESTING": True, "DATABASE": str(tmp_path / name), **cfg})


def reg(c, user="carol", pw="password123", email=None):
    body = {"username": user, "password": pw}
    if email:
        body["email"] = email
    return c.post("/api/register", json=body)


def test_old_database_is_migrated_without_data_loss(tmp_path):
    path = tmp_path / "old.sqlite"
    con = sqlite3.connect(path)
    con.executescript("""
      CREATE TABLE users (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT UNIQUE NOT NULL, password_hash TEXT NOT NULL);
      CREATE TABLE transactions (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL, date TEXT NOT NULL,
        description TEXT NOT NULL, amount REAL NOT NULL, type TEXT NOT NULL, category TEXT, confirmed INTEGER NOT NULL DEFAULT 0);
      CREATE TABLE contact_messages (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, email TEXT, subject TEXT, message TEXT, created_at TEXT);
      INSERT INTO users(username,password_hash) VALUES('legacy','x');
      INSERT INTO transactions(user_id,date,description,amount,type,category) VALUES(1,'2026-01-01','Old tx',5,'expense','Food');
    """)
    con.commit(); con.close()
    app = _mk({"TESTING": True, "DATABASE": str(path)})
    with app.app_context():
        from app.db import get_db
        db = get_db()
        ucols = {r["name"] for r in db.execute("PRAGMA table_info(users)")}
        tcols = {r["name"] for r in db.execute("PRAGMA table_info(transactions)")}
        assert {"email", "role", "is_active", "notify_email"} <= ucols and {"source", "import_id"} <= tcols
        row = db.execute("SELECT description, source FROM transactions").fetchone()
        assert (row["description"], row["source"]) == ("Old tx", "manual")
        assert db.execute("SELECT role,is_active FROM users").fetchone()["role"] == "user"
    _mk({"TESTING": True, "DATABASE": str(path)})  # second start is a no-op


def test_csrf_enforced_in_strict_mode(tmp_path):
    app = mk(tmp_path, CSRF_STRICT=True)
    c = app.test_client()
    assert c.post("/api/register", json={"username": "dave", "password": "password123"}).status_code == 403
    token = c.get("/login").data.decode().split('name="csrf-token" content="')[1].split('"')[0]
    ok = c.post("/api/register", json={"username": "dave", "password": "password123"}, headers={"X-CSRF-Token": token})
    assert ok.status_code == 201
    assert c.post("/api/transactions", json={}, headers={"X-CSRF-Token": "wrong"}).status_code == 403
    assert c.get("/api/transactions").status_code == 200  # GET needs no token


def test_security_headers(tmp_path):
    r = mk(tmp_path).test_client().get("/")
    assert r.headers["X-Content-Type-Options"] == "nosniff" and r.headers["X-Frame-Options"] == "DENY"


def test_login_rate_limit_and_case_insensitive_username(tmp_path):
    c = mk(tmp_path).test_client()
    reg(c, "Erin")
    c.post("/api/logout")
    assert c.post("/api/login", json={"username": "erin", "password": "password123"}).status_code == 200
    c.post("/api/logout")
    for _ in range(5):
        assert c.post("/api/login", json={"username": "erin", "password": "nope-nope"}).status_code == 401
    assert c.post("/api/login", json={"username": "erin", "password": "password123"}).status_code == 429


def test_register_validation_and_duplicate_email(tmp_path):
    c = mk(tmp_path).test_client()
    assert reg(c, "ab").status_code == 400
    assert reg(c, "frank", "short").status_code == 400
    assert reg(c, "frank", "password123", "not-an-email").status_code == 400
    assert reg(c, "frank", "password123", "f@example.com").status_code == 201
    assert reg(c, "grace", "password123", "F@Example.com").status_code == 409


def test_password_reset_flow(tmp_path):
    app = mk(tmp_path)
    c = app.test_client()
    reg(c, "heidi", "password123", "heidi@example.com")
    c.post("/api/logout")
    known = c.post("/api/forgot", json={"email": "heidi@example.com"}).get_json()
    unknown = c.post("/api/forgot", json={"email": "nobody@example.com"}).get_json()
    assert known == unknown                                   # no account enumeration
    outbox = app.extensions["outbox"]
    assert len(outbox) == 1 and outbox[0]["to"] == "heidi@example.com"
    token = outbox[0]["body"].split("/reset/")[1].split()[0]
    assert c.get(f"/reset/{token}").status_code == 200
    assert c.post("/api/reset", json={"token": token, "password": "short"}).status_code == 400
    assert c.post("/api/reset", json={"token": token, "password": "brandnewpass1"}).status_code == 200
    assert c.post("/api/reset", json={"token": token, "password": "anotherpass22"}).status_code == 400   # single use
    assert c.post("/api/login", json={"username": "heidi", "password": "password123"}).status_code == 401
    assert c.post("/api/login", json={"username": "heidi", "password": "brandnewpass1"}).status_code == 200
    assert c.post("/api/reset", json={"token": "garbage", "password": "brandnewpass1"}).status_code == 400


def test_expired_reset_token_rejected(tmp_path):
    app = mk(tmp_path)
    c = app.test_client()
    reg(c, "ivan", "password123", "ivan@example.com")
    c.post("/api/forgot", json={"email": "ivan@example.com"})
    token = app.extensions["outbox"][0]["body"].split("/reset/")[1].split()[0]
    with app.app_context():
        from app.db import get_db
        get_db().execute("UPDATE password_resets SET expires_at=1"); get_db().commit()
    assert c.post("/api/reset", json={"token": token, "password": "brandnewpass1"}).status_code == 400


def test_settings_change_password_export_delete(tmp_path):
    c = mk(tmp_path).test_client()
    reg(c, "judy")
    c.post("/api/transactions", json={"date": "2026-01-05", "description": "Rent", "amount": 500})
    assert c.get("/settings").status_code == 200
    assert c.patch("/api/account", json={"email": "judy@example.com", "notify_email": False}).status_code == 200
    acct = c.get("/api/account").get_json()
    assert acct["email"] == "judy@example.com" and acct["notify_email"] is False
    assert c.post("/api/account/password", json={"current": "wrong", "new": "newpassword1"}).status_code == 403
    assert c.post("/api/account/password", json={"current": "password123", "new": "newpassword1"}).status_code == 200
    exp = c.get("/api/account/export")
    assert exp.status_code == 200 and "attachment" in exp.headers["Content-Disposition"]
    data = exp.get_json()
    assert data["transactions"][0]["description"] == "Rent" and "password_hash" not in str(data)
    assert c.post("/api/account/delete", json={"password": "bad"}).status_code == 403
    assert c.post("/api/account/delete", json={"password": "newpassword1"}).status_code == 200
    assert c.get("/api/transactions").status_code == 401
    assert c.post("/api/login", json={"username": "judy", "password": "newpassword1"}).status_code == 401


def test_disabled_account_is_locked_out(tmp_path):
    app = mk(tmp_path)
    c = app.test_client()
    reg(c, "kevin")
    with app.app_context():
        from app.db import get_db
        get_db().execute("UPDATE users SET is_active=0"); get_db().commit()
    assert c.get("/api/transactions").status_code == 401
    assert c.post("/api/login", json={"username": "kevin", "password": "password123"}).status_code == 403


# ---------- statement import & duplicate detection ----------
import io as _io
import sys as _sys
import os as _os
_sys.path.insert(0, _os.path.dirname(__file__))
import pdf_factory as pf
from app.ml import dedupe as dd, statement as st


def upload(c, data, name="statement.pdf", password=None):
    form = {"file": (_io.BytesIO(data), name)}
    if password:
        form["password"] = password
    return c.post("/api/import/preview", data=form, content_type="multipart/form-data")


def confirm_all(c, prev, only_new=True):
    rows = [{k: r[k] for k in ("date", "description", "amount", "type")} for r in prev["rows"] if not (only_new and r["duplicate"])]
    return c.post("/api/import/confirm", json={"rows": rows, "filename": prev["filename"], "file_hash": prev["file_hash"], "kind": prev["kind"]})


def months(start_month, n, per_month=3):
    """Deterministic fake transactions for n consecutive months starting at start_month (1-12, year 2026)."""
    out = []
    for i in range(n):
        m = start_month + i
        out += [(date(2026, m, 2), f"UPI/SWIGGY/{m}", 400.0 + m, None), (date(2026, m, 3), "SALARY ACME CORP", None, 52000.0),
                (date(2026, m, 9), "NEFT-ELECTRICITY BILL", 1800.0 + m, None)][:per_month]
    return out


@pytest.mark.parametrize("layout,kw", [("columns", {}), ("columns", {"newest_first": True}), ("drcr", {}), ("signed", {}),
                                       ("columns_us", {}), ("columns", {"wrap": True}), ("columns", {"per_page": 3})])
def test_pdf_layouts_parse_correctly(layout, kw):
    rows, _ = st.parse_pages(st.extract_pages(pf.build(pf.SAMPLE, layout=layout, **kw)))
    exp = sorted((d.isoformat(), round(db or cr, 2), "expense" if db else "income") for d, _, db, cr in pf.SAMPLE)
    assert sorted((r["date"], r["amount"], r["type"]) for r in rows) == exp
    assert all(not r["description"].endswith(tuple("0123456789")) or "/" in r["description"] or " " in r["description"] for r in rows)


def test_password_protected_pdf():
    data = pf.build(pf.SAMPLE, password="s3cret!")
    with pytest.raises(st.StatementError) as e:
        st.extract_pages(data)
    assert e.value.code == "password_required"
    with pytest.raises(st.StatementError) as e:
        st.extract_pages(data, "wrong")
    assert e.value.code == "wrong_password"
    rows, _ = st.parse_pages(st.extract_pages(data, "s3cret!"))
    assert len(rows) == len(pf.SAMPLE)


def test_not_a_statement_and_scanned_pdf():
    from reportlab.pdfgen import canvas as cv
    buf = _io.BytesIO(); c = cv.Canvas(buf); c.showPage(); c.save()          # blank page, like a scanned image
    with pytest.raises(st.StatementError) as e:
        st.extract_pages(buf.getvalue())
    assert e.value.code == "scanned"
    buf = _io.BytesIO(); c = cv.Canvas(buf); c.drawString(50, 800, "Hello world, no money here"); c.showPage(); c.save()
    with pytest.raises(st.StatementError) as e:
        st.parse_pages(st.extract_pages(buf.getvalue()))
    assert e.value.code == "no_transactions"
    with pytest.raises(st.StatementError) as e:
        st.extract_pages(b"%PDF-1.4 garbage")
    assert e.value.code == "invalid"


def test_dedupe_unit_overlap_and_same_day_repeats():
    existing = [{"id": 1, "date": "2026-01-05", "description": "Swiggy order", "amount": 100.0, "type": "expense"}]
    inc = [{"date": "2026-01-05", "description": "UPI/SWIGGY/99887766", "amount": 100.0, "type": "expense"},   # same txn, bank wording
           {"date": "2026-01-05", "description": "UPI/SWIGGY/99887767", "amount": 100.0, "type": "expense"},   # genuine second purchase
           {"date": "2026-01-05", "description": "Swiggy order", "amount": 100.0, "type": "income"},            # other type -> new
           {"date": "2026-01-06", "description": "Swiggy order", "amount": 100.0, "type": "expense"}]           # other date -> new
    got = dd.find_duplicates(inc, existing)
    assert [g is not None for g in got] == [True, False, False, False]


def test_upload_three_months_then_six_adds_only_new_months(tmp_path):
    c = mk(tmp_path).test_client(); reg(c, "lena")
    first = upload(c, pf.build(months(1, 3))).get_json()
    assert first["counts"] == {"total": 9, "new": 9, "duplicate": 0}
    assert confirm_all(c, first).get_json()["imported"] == 9
    pdf6 = pf.build(months(1, 6))
    six = upload(c, pdf6).get_json()                              # includes the first 3 months again
    assert six["counts"] == {"total": 18, "new": 9, "duplicate": 9} and six["already_imported"] is None
    assert {r["date"][:7] for r in six["rows"] if not r["duplicate"]} == {"2026-04", "2026-05", "2026-06"}
    assert confirm_all(c, six).get_json()["imported"] == 9
    assert len(c.get("/api/transactions").get_json()) == 18      # exactly 6 months, no repeats
    again = upload(c, pdf6).get_json()                           # the very same file uploaded again
    assert again["counts"]["new"] == 0 and again["already_imported"] is not None
    # even if the client ignores the preview and posts everything, nothing is added twice
    r = confirm_all(c, again, only_new=False).get_json()
    assert r["imported"] == 0 and r["skipped_duplicates"] == 18
    assert len(c.get("/api/transactions").get_json()) == 18


def test_duplicates_against_manual_and_csv_entries(tmp_path):
    c = mk(tmp_path).test_client(); reg(c, "mike")
    c.post("/api/transactions", json={"date": "2026-01-02", "description": "Swiggy", "amount": 450, "type": "expense"})
    csv = b"date,description,amount\n2026-01-03,Salary,52000\n"
    assert c.post("/api/import/preview", data={"file": (_io.BytesIO(csv), "a.csv")}, content_type="multipart/form-data").status_code == 200
    prev = upload(c, pf.build(pf.SAMPLE)).get_json()
    dup = [r for r in prev["rows"] if r["duplicate"]]
    assert [r["amount"] for r in dup] == [450.0] and dup[0]["matched"] == "Swiggy"      # manual entry recognised


def test_same_day_identical_purchases_both_imported(tmp_path):
    c = mk(tmp_path).test_client(); reg(c, "nina")
    twin = [(date(2026, 2, 1), "POS COFFEE SHOP", 3.50, None), (date(2026, 2, 1), "POS COFFEE SHOP", 3.50, None)]
    prev = upload(c, pf.build(twin)).get_json()
    assert prev["counts"]["new"] == 2
    confirm_all(c, prev)
    assert len(c.get("/api/transactions").get_json()) == 2
    assert upload(c, pf.build(twin)).get_json()["counts"] == {"total": 2, "new": 0, "duplicate": 2}


def test_import_endpoint_password_flow_and_errors(tmp_path):
    c = mk(tmp_path).test_client(); reg(c, "omar")
    data = pf.build(pf.SAMPLE, password="pw12345")
    r = upload(c, data)
    assert r.status_code == 422 and r.get_json()["code"] == "password_required"
    assert upload(c, data, password="bad").get_json()["code"] == "wrong_password"
    ok = upload(c, data, password="pw12345")
    assert ok.status_code == 200 and ok.get_json()["counts"]["total"] == len(pf.SAMPLE)
    assert upload(c, b"hello", name="notes.docx").get_json()["code"] == "unsupported"
    assert c.post("/api/import/preview", data={}, content_type="multipart/form-data").status_code == 400
    assert c.post("/api/import/confirm", json={"rows": [{"date": "bad", "description": "x", "amount": 1, "type": "expense"}]}).status_code == 422


def test_import_history_undo_and_isolation(tmp_path):
    app = mk(tmp_path)
    c = app.test_client(); reg(c, "paula")
    prev = upload(c, pf.build(pf.SAMPLE)).get_json()
    cid = confirm_all(c, prev).get_json()["import_id"]
    assert c.get("/api/imports").get_json()[0]["rows_new"] == len(pf.SAMPLE)
    cats = {t["description"]: t["category"] for t in c.get("/api/transactions").get_json()}
    assert cats["UPI/SWIGGY/9876543210"] == "Food"                # imported rows are auto-categorised
    other = app.test_client(); reg(other, "quinn")
    assert other.delete(f"/api/imports/{cid}").status_code == 404
    assert c.delete(f"/api/imports/{cid}").get_json()["removed"] == len(pf.SAMPLE)
    assert c.get("/api/transactions").get_json() == [] and c.get("/api/imports").get_json() == []

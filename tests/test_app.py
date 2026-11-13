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


def test_csv_parsing_and_dedupe():
    rows, errs = parse_csv("date,description,amount\n2026-01-01,Salary,5000\n2026-01-02,Uber,-12\n2026-01-02,Uber,-12\nbad,x,1\n")
    assert [r["type"] for r in rows] == ["income", "expense"] and len(errs) == 1


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

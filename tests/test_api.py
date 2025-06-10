import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import budget_tool
import webapp
import api


def setup_client(tmp_path, monkeypatch):
    budget_tool.DB_FILE = tmp_path / "budget.db"
    webapp.setup_db()
    monkeypatch.setattr(budget_tool, "login_user", lambda t: "tester")
    budget_tool.add_user("tester")
    client = webapp.app.test_client()
    return client


def auth_hdr():
    return {"Authorization": "Bearer x"}


def test_categories_api(tmp_path, monkeypatch):
    client = setup_client(tmp_path, monkeypatch)
    resp = client.post("/api/categories", json={"name": "Food"}, headers=auth_hdr())
    assert resp.status_code == 201
    resp = client.get("/api/categories", headers=auth_hdr())
    assert resp.get_json() == ["Food"]


def test_accounts_api(tmp_path, monkeypatch):
    client = setup_client(tmp_path, monkeypatch)
    resp = client.post(
        "/api/accounts",
        json={"name": "Bank", "balance": 100, "payment": 0, "type": "Bank"},
        headers=auth_hdr(),
    )
    assert resp.status_code == 201
    resp = client.get("/api/accounts", headers=auth_hdr())
    data = resp.get_json()
    assert data and data[0]["name"] == "Bank"


def test_transactions_api(tmp_path, monkeypatch):
    client = setup_client(tmp_path, monkeypatch)
    client.post("/api/categories", json={"name": "Misc"}, headers=auth_hdr())
    resp = client.post(
        "/api/transactions",
        json={"category": "Misc", "amount": 5, "type": "expense"},
        headers=auth_hdr(),
    )
    assert resp.status_code == 201
    resp = client.get("/api/transactions", headers=auth_hdr())
    data = resp.get_json()
    assert data and data[0]["amount"] == 5


def test_goals_api(tmp_path, monkeypatch):
    client = setup_client(tmp_path, monkeypatch)
    client.post("/api/categories", json={"name": "Food"}, headers=auth_hdr())
    resp = client.post(
        "/api/goals",
        json={"category": "Food", "amount": 50},
        headers=auth_hdr(),
    )
    assert resp.status_code == 201
    resp = client.get("/api/goals", headers=auth_hdr())
    data = resp.get_json()
    assert data and data[0]["goal"] == 50

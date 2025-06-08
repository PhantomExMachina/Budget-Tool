import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import budget_tool
import webapp


def setup_app(tmp_path):
    budget_tool.DB_FILE = tmp_path / "budget.db"
    webapp.setup_db()
    return webapp.app.test_client()


def get_account_names(conn):
    cur = conn.execute("SELECT name FROM accounts ORDER BY name")
    return [r[0] for r in cur.fetchall()]


def test_update_accounts_delete(tmp_path):
    client = setup_app(tmp_path)
    # Add two accounts
    budget_tool.set_account("A1", 100, 10, "Bank")
    budget_tool.set_account("A2", 200, 20, "Bank")

    # Build form data mimicking the edit table
    data = {
        "delete": "A1",
        "old_0": "A1",
        "name_0": "A1",
        "balance_0": "100",
        "payment_0": "10",
        "type_0": "Bank",
        "old_1": "A2",
        "name_1": "A2",
        "balance_1": "200",
        "payment_1": "20",
        "type_1": "Bank",
    }
    client.post("/update-accounts", data=data)

    conn = budget_tool.get_connection()
    names = get_account_names(conn)
    conn.close()
    assert names == ["A2"]


def test_update_accounts_preserve_apr(tmp_path):
    client = setup_app(tmp_path)
    # create account with interest
    budget_tool.set_account("Card", 800, 100, "Credit Card", apr=20)

    data = {
        "old_0": "Card",
        "name_0": "Card",
        "balance_0": "800",
        "payment_0": "100",
        "type_0": "Credit Card",
    }

    client.post("/update-accounts", data=data)

    conn = budget_tool.get_connection()
    cur = conn.execute("SELECT balance, monthly_payment, apr FROM accounts WHERE name=?", ("Card",))
    row = cur.fetchone()
    conn.close()

    assert row["apr"] == 20
    months = budget_tool.months_to_payoff(row["balance"], row["monthly_payment"], row["apr"])
    months_no_interest = budget_tool.months_to_payoff(row["balance"], row["monthly_payment"], 0)
    assert months > months_no_interest


def test_forecast_route(tmp_path):
    client = setup_app(tmp_path)
    budget_tool.set_account("Bank", 100, acct_type="Bank")
    resp = client.get("/forecast")
    assert resp.status_code == 200
    assert b"Account Forecast" in resp.data


import sys
from pathlib import Path
import io

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import budget_tool
import webapp


def setup_app(tmp_path):
    budget_tool.DB_FILE = tmp_path / "budget.db"
    webapp.setup_db()
    return webapp.app.test_client()


def login(client, monkeypatch):
    monkeypatch.setattr(budget_tool, "login_user", lambda t: "tester")
    client.post("/login", data={"token": "x"})


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


def test_forecast_route(tmp_path, monkeypatch):
    client = setup_app(tmp_path)
    budget_tool.set_account("Bank", 100, acct_type="Bank")
    login(client, monkeypatch)
    resp = client.get("/forecast")
    assert resp.status_code == 200
    assert b"Account Forecast" in resp.data


def test_auto_scan_route(tmp_path, monkeypatch):
    client = setup_app(tmp_path)
    login(client, monkeypatch)
    data1 = b"date,description,amount\n2023-01-01,Gym,10\n"
    data2 = b"date,description,amount\n2023-02-01,Gym,10\n"
    def build_data():
        return {
            "statement": [
                (io.BytesIO(data1), "jan.csv"),
                (io.BytesIO(data2), "feb.csv"),
            ]
        }

    resp = client.post("/auto-scan", data=build_data(), content_type="multipart/form-data")
    assert resp.status_code == 200
    assert b"Gym" in resp.data
    assert b"name=\"add_0\"" in resp.data

    save = {"desc_0": "Gym", "amt_0": "10", "add_0": "on"}
    client.post("/auto-scan", data=save)

    resp2 = client.post("/auto-scan", data=build_data(), content_type="multipart/form-data")
    assert b"name=\"add_0\"" not in resp2.data


def test_nav_contains_auto_scan(tmp_path):
    client = setup_app(tmp_path)
    resp = client.get("/")
    assert resp.status_code == 200
    assert b"/auto-scan" in resp.data


def test_protected_requires_login(tmp_path):
    client = setup_app(tmp_path)
    resp = client.get("/manage")
    assert resp.status_code == 200


def test_delete_monthly_expense(tmp_path):
    client = setup_app(tmp_path)
    budget_tool.add_category("Misc")
    budget_tool.add_monthly_expense("Gym", 10)
    budget_tool.add_transaction("Misc", 10, "expense", "Gym")

    resp = client.post("/delete-monthly/Gym")
    assert resp.status_code == 302

    conn = budget_tool.get_connection()
    cur = conn.execute(
        "SELECT count(*) FROM monthly_expenses WHERE description=?", ("Gym",)
    )
    assert cur.fetchone()[0] == 0
    cur = conn.execute(
        "SELECT count(*) FROM transactions WHERE description=?", ("Gym",)
    )
    assert cur.fetchone()[0] == 0
    conn.close()


def test_monthly_expense_creates_transaction(tmp_path):
    _ = setup_app(tmp_path)
    budget_tool.add_category("Misc")
    budget_tool.add_monthly_expense("Gym", 10)

    conn = budget_tool.get_connection()
    cur = conn.execute(
        "SELECT count(*) FROM transactions WHERE description=?", ("Gym",)
    )
    assert cur.fetchone()[0] == 1
    conn.close()


def test_delete_transaction_removes_monthly(tmp_path):
    client = setup_app(tmp_path)
    budget_tool.add_category("Misc")
    budget_tool.add_monthly_expense("Gym", 10)

    conn = budget_tool.get_connection()
    cur = conn.execute(
        "SELECT id FROM transactions WHERE description=?", ("Gym",)
    )
    tid = cur.fetchone()["id"]
    conn.close()

    client.post(f"/delete/{tid}")

    conn = budget_tool.get_connection()
    cur = conn.execute(
        "SELECT count(*) FROM monthly_expenses WHERE description=?", ("Gym",)
    )
    assert cur.fetchone()[0] == 0
    conn.close()


def test_monthly_income_routes(tmp_path, monkeypatch):
    client = setup_app(tmp_path)
    budget_tool.add_category("Job")
    login(client, monkeypatch)
    client.post(
        "/add-monthly-income",
        data={"desc": "Salary", "amount": "50", "category": "Job"},
    )
    resp = client.get("/manage")
    assert b"Salary" in resp.data
    client.post("/delete-monthly-income/Salary")
    resp2 = client.get("/manage")
    assert b"Salary" not in resp2.data


def test_history_date_filter(tmp_path, monkeypatch):
    client = setup_app(tmp_path)
    budget_tool.add_category("Misc")
    budget_tool.add_transaction("Misc", 5, "expense", "old")
    budget_tool.add_transaction("Misc", 5, "expense", "new")
    conn = budget_tool.get_connection()
    cur = conn.execute(
        "SELECT id FROM transactions WHERE description='old'"
    )
    old_id = cur.fetchone()["id"]
    cur = conn.execute(
        "SELECT id FROM transactions WHERE description='new'"
    )
    new_id = cur.fetchone()["id"]
    conn.execute(
        "UPDATE transactions SET created_at='2023-01-01' WHERE id=?",
        (old_id,),
    )
    conn.execute(
        "UPDATE transactions SET created_at='2023-02-01' WHERE id=?",
        (new_id,),
    )
    conn.commit()
    conn.close()
    login(client, monkeypatch)
    resp = client.get("/history?start=2023-01-15&end=2023-02-28")
    assert b"new" in resp.data
    assert b"old" not in resp.data


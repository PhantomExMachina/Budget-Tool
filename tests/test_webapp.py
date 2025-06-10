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


def get_csrf(client, path="/manage"):
    resp = client.get(path)
    import re
    match = re.search(r'name="csrf_token" value="([^"]+)"', resp.get_data(as_text=True))
    return match.group(1) if match else None


def login(client, monkeypatch):
    monkeypatch.setattr(budget_tool, "login_user", lambda t: "tester")
    token = get_csrf(client, "/login")
    client.post("/login", data={"token": "x", "csrf_token": token})


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
    token = get_csrf(client)
    data["csrf_token"] = token
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

    token = get_csrf(client)
    data["csrf_token"] = token
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
    data1 = b"date,description,amount\n2023-01-01,Gym,-10\n"
    data2 = b"date,description,amount\n2023-02-01,Gym,-10\n"
    def build_data():
        return {
            "statement": [
                (io.BytesIO(data1), "jan.csv"),
                (io.BytesIO(data2), "feb.csv"),
            ]
        }

    token = get_csrf(client, "/auto-scan")
    resp = client.post(
        "/auto-scan",
        data=dict(build_data(), csrf_token=token),
        content_type="multipart/form-data",
    )
    assert resp.status_code == 200
    assert b"Gym" in resp.data
    assert b"name=\"add_0\"" in resp.data

    save = {"desc_0": "Gym", "amt_0": "10", "add_0": "on", "csrf_token": token}
    client.post("/auto-scan", data=save)

    token = get_csrf(client, "/auto-scan")
    resp2 = client.post(
        "/auto-scan",
        data=dict(build_data(), csrf_token=token),
        content_type="multipart/form-data",
    )
    assert b"name=\"add_0\"" not in resp2.data


def test_auto_scan_one_time(tmp_path, monkeypatch):
    client = setup_app(tmp_path)
    login(client, monkeypatch)
    data1 = b"date,description,amount\n2023-01-01,Gym,-10\n2023-01-02,Coffee,-5\n"
    data2 = b"date,description,amount\n2023-02-01,Gym,-10\n"

    token = get_csrf(client, "/auto-scan")
    client.post(
        "/auto-scan",
        data={
            "statement": [
                (io.BytesIO(data1), "jan.csv"),
                (io.BytesIO(data2), "feb.csv"),
            ],
            "csrf_token": token,
        },
        content_type="multipart/form-data",
    )

    rows = budget_tool.get_one_time_expenses()
    assert any(r[1] == "Coffee" for r in rows)
    oid = next(r[0] for r in rows if r[1] == "Coffee")
    token = get_csrf(client, "/auto-scan")
    client.post(f"/convert-one-time/{oid}", data={"csrf_token": token})
    assert not any(r[1] == "Coffee" for r in budget_tool.get_one_time_expenses())
    assert budget_tool.monthly_expense_exists("Coffee")


def test_delete_one_time(tmp_path, monkeypatch):
    client = setup_app(tmp_path)
    login(client, monkeypatch)
    from datetime import datetime
    budget_tool.add_one_time_expense("Temp", 5, datetime(2023, 1, 1))
    oid = budget_tool.get_one_time_expenses()[0][0]
    token = get_csrf(client, "/auto-scan")
    resp = client.post("/delete-one-time", data={"delete": str(oid), "csrf_token": token})
    assert resp.status_code == 302
    assert budget_tool.get_one_time_expenses() == []


def test_auto_scan_ignore_duplicates(tmp_path, monkeypatch):
    client = setup_app(tmp_path)
    login(client, monkeypatch)
    data1 = b"date,description,amount\n2023-01-01,Item,-5\n"
    data2 = b"date,description,amount\n2023-02-01,Other,-2\n"
    token = get_csrf(client, "/auto-scan")
    client.post(
        "/auto-scan",
        data={
            "statement": [
                (io.BytesIO(data1), "jan.csv"),
                (io.BytesIO(data2), "feb.csv"),
            ],
            "csrf_token": token,
        },
        content_type="multipart/form-data",
    )
    token = get_csrf(client, "/auto-scan")
    client.post(
        "/auto-scan",
        data={
            "statement": [
                (io.BytesIO(data1), "jan.csv"),
                (io.BytesIO(data2), "feb.csv"),
            ],
            "csrf_token": token,
        },
        content_type="multipart/form-data",
    )
    rows = [r for r in budget_tool.get_one_time_expenses() if r[1] == "Item"]
    assert len(rows) == 1


def test_nav_contains_auto_scan(tmp_path):
    client = setup_app(tmp_path)
    resp = client.get("/")
    assert resp.status_code == 200
    assert b"/auto-scan" in resp.data


def test_nav_contains_budget(tmp_path):
    client = setup_app(tmp_path)
    resp = client.get("/")
    assert resp.status_code == 200
    assert b"/budget" in resp.data


def test_protected_requires_login(tmp_path):
    client = setup_app(tmp_path)
    resp = client.get("/manage")
    assert resp.status_code == 200


def test_delete_monthly_expense(tmp_path):
    client = setup_app(tmp_path)
    budget_tool.add_category("Misc")
    budget_tool.add_monthly_expense("Gym", 10)
    budget_tool.add_transaction("Misc", 10, "expense", "Gym")

    token = get_csrf(client)
    resp = client.post("/delete-monthly/Gym", data={"csrf_token": token})
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


def test_delete_monthly_multiple(tmp_path):
    client = setup_app(tmp_path)
    budget_tool.add_category("Misc")
    budget_tool.add_monthly_expense("Gym", 10)
    budget_tool.add_monthly_expense("Net", 20)
    token = get_csrf(client, "/auto-scan")
    resp = client.post(
        "/delete-monthly",
        data={"delete": ["Gym", "Net"], "csrf_token": token},
    )
    assert resp.status_code == 302
    assert budget_tool.get_monthly_expenses() == []


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

    token = get_csrf(client)
    client.post(f"/delete/{tid}", data={"csrf_token": token})

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
    token = get_csrf(client)
    client.post(
        "/add-monthly-income",
        data={"desc": "Salary", "amount": "50", "category": "Job", "csrf_token": token},
    )
    resp = client.get("/manage")
    assert b"Salary" in resp.data
    token = get_csrf(client)
    client.post("/delete-monthly-income/Salary", data={"csrf_token": token})
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


def test_csrf_required(tmp_path):
    client = setup_app(tmp_path)
    resp = client.post("/add-category", data={"name": "X"})
    assert resp.status_code == 400
    token = get_csrf(client)
    resp = client.post("/add-category", data={"name": "X", "csrf_token": token})
    assert resp.status_code == 302


def test_dashboard_data(tmp_path, monkeypatch):
    client = setup_app(tmp_path)
    budget_tool.add_category("Food")
    budget_tool.add_transaction("Food", 10, "expense")
    login(client, monkeypatch)
    resp = client.get("/dashboard-data")
    assert resp.status_code == 200
    data = resp.get_json()
    assert "categories" in data
    assert data["categories"][0][0] == "Food"


def test_budget_route(tmp_path, monkeypatch):
    client = setup_app(tmp_path)
    budget_tool.set_account("Loan", 1000, 50, "Loan")
    login(client, monkeypatch)
    resp = client.get("/budget")
    assert resp.status_code == 200
    assert b"Budget" in resp.data


def test_budget_excludes_bank(tmp_path, monkeypatch):
    client = setup_app(tmp_path)
    budget_tool.set_account("Checking", 100, 0, "Bank")
    budget_tool.set_account("Loan", 500, 50, "Loan")
    login(client, monkeypatch)
    resp = client.get("/budget")
    assert b"Checking" not in resp.data
    assert b"Loan" in resp.data


def test_commit_extra_payment(tmp_path, monkeypatch):
    client = setup_app(tmp_path)
    budget_tool.set_account("Loan", 1000, 50, "Loan")
    login(client, monkeypatch)
    token = get_csrf(client, "/budget")
    client.post(
        "/commit-extra",
        data={"account": "Loan", "extra": "25", "csrf_token": token},
    )
    amt = budget_tool.get_monthly_expense_amount("Extra Payment - Loan")
    assert amt == 25
    assets, debts = webapp.get_account_forecast(1)
    loan = next(d for d in debts if d["name"] == "Loan")
    exp = budget_tool.account_balance_after_months(1000, 75, 0, 0, 0, 0, 1)
    assert loan["future"] == exp


def test_update_extra_payment(tmp_path, monkeypatch):
    client = setup_app(tmp_path)
    budget_tool.set_account("Loan", 1000, 50, "Loan")
    login(client, monkeypatch)
    token = get_csrf(client, "/budget")
    client.post(
        "/commit-extra",
        data={"account": "Loan", "extra": "25", "csrf_token": token},
    )
    # update to new amount
    token = get_csrf(client, "/budget")
    client.post(
        "/commit-extra",
        data={"account": "Loan", "extra": "40", "csrf_token": token},
    )
    amt = budget_tool.get_monthly_expense_amount("Extra Payment - Loan")
    assert amt == 40
    # remove extra payment
    token = get_csrf(client, "/budget")
    client.post(
        "/commit-extra",
        data={"account": "Loan", "extra": "0", "csrf_token": token},
    )
    assert (
        budget_tool.get_monthly_expense_amount("Extra Payment - Loan") is None
    )


def test_budget_leftover_after_commit(tmp_path, monkeypatch):
    client = setup_app(tmp_path)
    budget_tool.add_category("Job")
    budget_tool.add_category("Rent")
    budget_tool.add_transaction("Job", 2000, "income", "Paycheck")
    budget_tool.add_monthly_expense("Rent", 1000, "Rent")
    budget_tool.set_account("Loan", 1000, 50, "Loan")
    login(client, monkeypatch)
    token = get_csrf(client, "/budget")
    client.post(
        "/commit-extra",
        data={"account": "Loan", "extra": "500", "csrf_token": token},
    )
    resp = client.get("/budget")
    import re
    match = re.search(r'id="leftover"[^>]*>([0-9.,]+)</span>', resp.get_data(as_text=True))
    assert match
    leftover_val = float(match.group(1).replace(",", ""))
    assert leftover_val == 500.0


def test_budget_leftover_classes(tmp_path, monkeypatch):
    client = setup_app(tmp_path)
    budget_tool.add_category("Job")
    budget_tool.add_transaction("Job", 1000, "income", "Paycheck")
    budget_tool.set_account("Loan", 1000, 50, "Loan")
    # set extra to trigger warning
    budget_tool.add_monthly_expense("Extra Payment - Loan", 850, "Extra Payment")
    login(client, monkeypatch)
    resp = client.get("/budget")
    assert b'class="text-warning"' in resp.data
    assert b'id="leftover-icon"' in resp.data
    assert b'display:inline' in resp.data
    # set extra to trigger danger
    budget_tool.add_monthly_expense("Extra Payment - Loan", 950, "Extra Payment")
    resp = client.get("/budget")
    assert b'class="text-danger"' in resp.data
    assert b'id="leftover-icon"' in resp.data
    assert b'display:inline' in resp.data


import sqlite3
import subprocess
from pathlib import Path
from datetime import datetime


SCRIPT = Path(__file__).resolve().parents[1] / "budget_tool.py"


def run_cli(tmp_path, *args, db_path=None):
    script_copy = tmp_path / "budget_tool.py"
    script_copy.write_bytes(SCRIPT.read_bytes())
    cmd = ["python3", str(script_copy)]
    if db_path:
        cmd += ["--db", str(db_path)]
    cmd.extend(args)
    result = subprocess.run(
        cmd,
        cwd=tmp_path,
        text=True,
        capture_output=True,
    )
    return result


def test_init_creates_db(tmp_path):
    result = run_cli(tmp_path, "init")
    assert (tmp_path / "budget.db").exists()
    assert "Database initialized" in result.stdout


def test_add_category_and_duplicate(tmp_path):
    run_cli(tmp_path, "init")
    out1 = run_cli(tmp_path, "add-category", "Food").stdout
    assert "Category 'Food' added" in out1
    out2 = run_cli(tmp_path, "add-category", "Food").stdout
    assert "already exists" in out2
    conn = sqlite3.connect(tmp_path / "budget.db")
    count = conn.execute("SELECT count(*) FROM categories").fetchone()[0]
    conn.close()
    assert count == 1


def test_income_expense_balance(tmp_path):
    run_cli(tmp_path, "init")
    run_cli(tmp_path, "add-category", "Salary")
    run_cli(tmp_path, "add-income", "Salary", "1000")
    run_cli(tmp_path, "add-expense", "Salary", "200")
    bal = run_cli(tmp_path, "balance", "Salary").stdout
    assert "Income: 1,000.00" in bal
    assert "Expense: 200.00" in bal
    assert "Balance: 800.00" in bal


def test_totals_output(tmp_path):
    run_cli(tmp_path, "init")
    run_cli(tmp_path, "add-category", "Job")
    run_cli(tmp_path, "add-category", "Groceries")
    run_cli(tmp_path, "add-income", "Job", "1500")
    run_cli(tmp_path, "add-expense", "Groceries", "500")
    totals = run_cli(tmp_path, "totals").stdout
    assert "Total Income: 1,500.00" in totals
    assert "Total Expense: 500.00" in totals
    assert "Net Balance: 1,000.00" in totals
    assert "Total Assets: 0.00" in totals


def test_goal_warning(tmp_path):
    run_cli(tmp_path, "init")
    run_cli(tmp_path, "add-category", "Food")
    run_cli(tmp_path, "set-goal", "Food", "50")
    warn = run_cli(tmp_path, "add-expense", "Food", "60").stdout
    assert "Warning" in warn


def test_export_csv(tmp_path):
    run_cli(tmp_path, "init")
    run_cli(tmp_path, "add-category", "Job")
    run_cli(tmp_path, "add-income", "Job", "100")
    out = tmp_path / "data.csv"
    run_cli(tmp_path, "export-csv", "--output", str(out))
    assert out.exists()
    lines = out.read_text().splitlines()
    assert lines[0].startswith("category")
    assert len(lines) == 2


def test_history_output(tmp_path):
    run_cli(tmp_path, "init")
    run_cli(tmp_path, "add-category", "Misc")
    run_cli(tmp_path, "add-expense", "Misc", "5", "-d", "snack")
    hist = run_cli(tmp_path, "history").stdout
    assert "snack" in hist


def test_item_name_recorded(tmp_path):
    run_cli(tmp_path, "init")
    run_cli(tmp_path, "add-category", "Utilities")
    run_cli(tmp_path, "add-expense", "Utilities", "30", "--item", "Water")
    hist = run_cli(tmp_path, "history").stdout
    assert "Water" in hist


def test_custom_db_path(tmp_path):
    custom = tmp_path / "custom.db"
    run_cli(tmp_path, "init", db_path=custom)
    assert custom.exists()


def test_delete_account(tmp_path):
    run_cli(tmp_path, "init")
    run_cli(tmp_path, "set-account", "Bank", "50")
    before = run_cli(tmp_path, "list-accounts").stdout
    assert "Bank" in before
    run_cli(tmp_path, "delete-account", "Bank")
    after = run_cli(tmp_path, "list-accounts").stdout
    assert "Bank" not in after


def test_bank_balance_projection(tmp_path):
    run_cli(tmp_path, "init")
    run_cli(tmp_path, "add-category", "Job")
    run_cli(tmp_path, "add-income", "Job", "100")
    import budget_tool
    budget_tool.DB_FILE = tmp_path / "budget.db"
    budget_tool.set_account("Bank", 1000, acct_type="Bank")
    out = run_cli(tmp_path, "bank-balance", "3").stdout
    assert "1,300.00" in out


def test_totals_negative_warning(tmp_path):
    run_cli(tmp_path, "init")
    run_cli(tmp_path, "add-category", "Job")
    run_cli(tmp_path, "add-income", "Job", "100")
    run_cli(tmp_path, "add-category", "Food")
    run_cli(tmp_path, "add-expense", "Food", "150")
    import budget_tool
    budget_tool.DB_FILE = tmp_path / "budget.db"
    budget_tool.set_account("Bank", 200, acct_type="Bank")
    out = run_cli(tmp_path, "totals").stdout
    assert "Net Balance: -50.00" in out
    assert "negative in about 4 months" in out
    assert "Total Assets: 200.00" in out


def test_months_to_payoff_interest(tmp_path):
    run_cli(tmp_path, "init")
    from budget_tool import months_to_payoff

    assert months_to_payoff(1000, 100, 0) == 10
    assert months_to_payoff(1000, 100, 20) > 10


def test_set_account_with_apr_cli(tmp_path):
    run_cli(tmp_path, "init")
    run_cli(
        tmp_path,
        "set-account",
        "Card",
        "5000",
        "--payment",
        "50",
        "--apr",
        "10",
    )
    out = run_cli(tmp_path, "list-accounts").stdout
    assert "Card" in out
    months = None
    for line in out.splitlines():
        if "Card" in line:
            months = int(line.split("months")[1].split(")")[0].strip())
            break
    assert months and months > 100


def test_totals_forecast(tmp_path):
    run_cli(tmp_path, "init")
    run_cli(tmp_path, "add-category", "Job")
    run_cli(tmp_path, "add-income", "Job", "1000")
    import budget_tool
    budget_tool.DB_FILE = tmp_path / "budget.db"
    budget_tool.set_account("Card", 1000, payment=100, apr=12, acct_type="Credit Card")
    out = run_cli(tmp_path, "totals", "--months", "1").stdout
    assert "Account forecast after 1 month" in out
    assert "Card" in out
    assert "910.00" in out


def test_forecast_command(tmp_path):
    run_cli(tmp_path, "init")
    import budget_tool
    budget_tool.DB_FILE = tmp_path / "budget.db"
    budget_tool.set_account("Bank", 1000, acct_type="Bank")
    budget_tool.set_account("Card", 500, payment=50, acct_type="Credit Card")
    out = run_cli(tmp_path, "forecast", "--months", "2").stdout
    assert "Accounts with funds after 2 months" in out
    assert "Accounts with money owed after 2 months" in out
    assert "Bank" in out
    assert "Card" in out


def test_parse_statement_csv(tmp_path):
    csv_text = "date,description,amount\n2023-01-01,Gym,10\n2023-01-02,Netflix,15"
    f = tmp_path / "s.csv"
    f.write_text(csv_text)
    from budget_tool import parse_statement_csv

    records = parse_statement_csv(f)
    assert len(records) == 2
    assert records[0].description == "Gym"
    assert records[0].amount == 10
    assert records[0].category is None


def test_parse_statement_csv_posting_date(tmp_path):
    csv_text = "Posting Date,Description,Amount,Transaction Category\n" \
        "2023-01-01,Coffee,5,Drinks"
    f = tmp_path / "s2.csv"
    f.write_text(csv_text)
    from budget_tool import parse_statement_csv

    records = parse_statement_csv(f)
    assert len(records) == 1
    assert records[0].description == "Coffee"
    assert records[0].amount == 5
    assert records[0].date == datetime(2023, 1, 1)
    assert records[0].category == "Drinks"


def test_parse_statement_csv_tab_delimited(tmp_path):
    csv_text = "date\tdescription\tamount\n2023-01-01\tGym\t10"
    f = tmp_path / "tab.tsv"
    f.write_text(csv_text)
    from budget_tool import parse_statement_csv

    records = parse_statement_csv(f)
    assert len(records) == 1
    assert records[0].description == "Gym"
    assert records[0].amount == 10


def test_parse_statement_csv_date_formats(tmp_path):
    csv_text = (
        "date,description,amount\n20230102,Gym,20\n01/03/2023,Store,5"
    )
    f = tmp_path / "dates.csv"
    f.write_text(csv_text)
    from budget_tool import parse_statement_csv

    records = parse_statement_csv(f)
    assert len(records) == 2
    assert records[0].date == datetime(2023, 1, 2)
    assert records[1].date == datetime(2023, 1, 3)


def test_parse_statement_csv_category_detection(tmp_path):
    csv_text = (
        "date,description,amount,category\n"
        "2023-01-01,Gym,10,Health"
    )
    f = tmp_path / "cat.csv"
    f.write_text(csv_text)
    from budget_tool import parse_statement_csv

    records = parse_statement_csv(f)
    assert len(records) == 1
    assert records[0].category == "Health"


def test_find_recurring_expenses():
    from budget_tool import TransactionRecord, find_recurring_expenses
    rec1 = [
        TransactionRecord(datetime(2023, 1, 1), "Gym", 10),
        TransactionRecord(datetime(2023, 1, 2), "Store", 5),
    ]
    rec2 = [
        TransactionRecord(datetime(2023, 2, 1), "Gym", 10.05),
        TransactionRecord(datetime(2023, 2, 5), "Other", 3),
    ]
    res = find_recurring_expenses([rec1, rec2])
    names = [r[0] for r in res]
    assert "Gym" in names


def test_find_recurring_expenses_day_window():
    """Charges on adjacent days should match within the window."""
    from budget_tool import TransactionRecord, find_recurring_expenses

    jan = [TransactionRecord(datetime(2023, 1, 20), "Service", 30)]
    feb = [TransactionRecord(datetime(2023, 2, 21), "Service", 29.9)]

    res = find_recurring_expenses([jan, feb], day_window=1)
    assert res and res[0][0] == "Service"


def test_find_recurring_expenses_positive_amount():
    """Negative amounts should be returned as positive values."""
    from budget_tool import TransactionRecord, find_recurring_expenses

    jan = [TransactionRecord(datetime(2023, 1, 1), "Gym", -10)]
    feb = [TransactionRecord(datetime(2023, 2, 1), "Gym", -10)]

    res = find_recurring_expenses([jan, feb])
    assert res and res[0][1] == 10


def test_add_monthly_expense_abs(tmp_path):
    import budget_tool

    budget_tool.DB_FILE = tmp_path / "budget.db"
    budget_tool.init_db()
    budget_tool.add_category("Misc")
    budget_tool.add_monthly_expense("Gym", -20)

    conn = budget_tool.get_connection()
    amt = conn.execute(
        "SELECT amount FROM monthly_expenses WHERE description=?",
        ("Gym",),
    ).fetchone()[0]
    conn.close()
    assert amt == 20


def test_monthly_income_functions(tmp_path):
    import budget_tool

    budget_tool.DB_FILE = tmp_path / "budget.db"
    budget_tool.init_db()
    budget_tool.add_category("Job")
    budget_tool.add_monthly_income("Salary", 100, "Job")

    conn = budget_tool.get_connection()
    cur = conn.execute(
        "SELECT count(*) FROM monthly_incomes WHERE description=?",
        ("Salary",),
    )
    assert cur.fetchone()[0] == 1
    cur = conn.execute(
        "SELECT count(*) FROM transactions WHERE description=?",
        ("Salary",),
    )
    assert cur.fetchone()[0] == 1
    conn.close()


def test_monthly_expense_cli(tmp_path):
    run_cli(tmp_path, "init")
    run_cli(tmp_path, "add-monthly-expense", "Gym", "20")
    out = run_cli(tmp_path, "list-monthly-expenses").stdout
    assert "Gym" in out
    run_cli(tmp_path, "delete-monthly-expense", "Gym")
    out2 = run_cli(tmp_path, "list-monthly-expenses").stdout
    assert "Gym" not in out2


def test_one_time_expense_functions(tmp_path):
    import budget_tool

    budget_tool.DB_FILE = tmp_path / "budget.db"
    budget_tool.init_db()
    dt = datetime(2023, 1, 1)
    budget_tool.add_one_time_expense("Laptop", 1000, dt)
    rows = budget_tool.get_one_time_expenses()
    assert rows and rows[0][1] == "Laptop"
    assert budget_tool.one_time_total() == 1000
    oid = rows[0][0]
    budget_tool.convert_one_time_to_monthly(oid)
    assert budget_tool.monthly_expense_exists("Laptop")
    assert budget_tool.get_one_time_expenses() == []

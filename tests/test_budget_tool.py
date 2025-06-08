import sqlite3
import subprocess
from pathlib import Path


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
    assert "Income: 1000.00" in bal
    assert "Expense: 200.00" in bal
    assert "Balance: 800.00" in bal


def test_totals_output(tmp_path):
    run_cli(tmp_path, "init")
    run_cli(tmp_path, "add-category", "Job")
    run_cli(tmp_path, "add-category", "Groceries")
    run_cli(tmp_path, "add-income", "Job", "1500")
    run_cli(tmp_path, "add-expense", "Groceries", "500")
    totals = run_cli(tmp_path, "totals").stdout
    assert "Total Income: 1500.00" in totals
    assert "Total Expense: 500.00" in totals
    assert "Net Balance: 1000.00" in totals


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


def test_custom_db_path(tmp_path):
    custom = tmp_path / "custom.db"
    run_cli(tmp_path, "init", db_path=custom)
    assert custom.exists()

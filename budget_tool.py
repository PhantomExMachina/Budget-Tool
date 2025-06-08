#!/usr/bin/env python3
"""Simple CLI-based budgeting tool using SQLite."""

import argparse
import csv
import os
import sqlite3
from pathlib import Path
from datetime import datetime
import math

try:
    import auth
except Exception:  # pragma: no cover - optional dependency
    auth = None

DEFAULT_DB = Path(__file__).with_name("budget.db")
DB_FILE = Path(os.environ.get("BUDGET_DB", DEFAULT_DB))


def get_connection():
    """Return a SQLite connection using the configured database file."""
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    """Create database tables and ensure a default user exists."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                auth_uid TEXT UNIQUE
            )"""
    )
    cur.execute(
        """CREATE TABLE IF NOT EXISTS categories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE NOT NULL
            )"""
    )
    cur.execute(
        """CREATE TABLE IF NOT EXISTS transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                category_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                amount REAL NOT NULL,
                type TEXT CHECK(type IN ('income','expense')) NOT NULL,
                description TEXT,
                item_name TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY(category_id) REFERENCES categories(id),
                FOREIGN KEY(user_id) REFERENCES users(id)
            )"""
    )
    cur.execute(
        """CREATE TABLE IF NOT EXISTS goals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                category_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                amount REAL NOT NULL,
                UNIQUE(category_id, user_id),
                FOREIGN KEY(category_id) REFERENCES categories(id),
                FOREIGN KEY(user_id) REFERENCES users(id)
            )"""
    )
    cur.execute(
        """CREATE TABLE IF NOT EXISTS accounts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE NOT NULL,
                balance REAL NOT NULL,
                monthly_payment REAL DEFAULT 0,
                type TEXT DEFAULT 'Other',
                apr REAL DEFAULT 0,
                escrow REAL DEFAULT 0,
                insurance REAL DEFAULT 0,
                tax REAL DEFAULT 0
            )"""
    )
    # add item_name column if upgrading from older DB
    cur.execute("PRAGMA table_info(transactions)")
    cols = [r[1] for r in cur.fetchall()]
    if "item_name" not in cols:
        cur.execute("ALTER TABLE transactions ADD COLUMN item_name TEXT")
    # upgrade existing accounts table with new columns if missing
    cur.execute("PRAGMA table_info(accounts)")
    acct_cols = [r[1] for r in cur.fetchall()]
    if "type" not in acct_cols:
        cur.execute("ALTER TABLE accounts ADD COLUMN type TEXT DEFAULT 'Other'")
    if "apr" not in acct_cols:
        cur.execute("ALTER TABLE accounts ADD COLUMN apr REAL DEFAULT 0")
    if "escrow" not in acct_cols:
        cur.execute("ALTER TABLE accounts ADD COLUMN escrow REAL DEFAULT 0")
    if "insurance" not in acct_cols:
        cur.execute("ALTER TABLE accounts ADD COLUMN insurance REAL DEFAULT 0")
    if "tax" not in acct_cols:
        cur.execute("ALTER TABLE accounts ADD COLUMN tax REAL DEFAULT 0")
    # ensure default user exists
    cur.execute("INSERT OR IGNORE INTO users(username) VALUES('default')")
    conn.commit()
    conn.close()


def add_category(name: str):
    """Add a new spending category."""
    conn = get_connection()
    try:
        conn.execute("INSERT INTO categories(name) VALUES(?)", (name,))
        conn.commit()
        print(f"Category '{name}' added.")
    except sqlite3.IntegrityError:
        print(f"Category '{name}' already exists.")
    finally:
        conn.close()


def calc_totals(user: str = "default") -> tuple[float, float, float]:
    """Return total income, expense and net for a user."""
    conn = get_connection()
    user_id = get_user_id(conn, user)
    cur = conn.execute(
        (
            "SELECT type, SUM(amount) FROM transactions WHERE user_id=? "
            "GROUP BY type"
        ),
        (user_id,),
    )
    totals = {row[0]: row[1] or 0 for row in cur.fetchall()}
    conn.close()
    income = totals.get("income", 0)
    expense = totals.get("expense", 0)
    return income, expense, income - expense


def total_bank_balance() -> float:
    """Return the sum of all bank account balances."""
    conn = get_connection()
    cur = conn.execute("SELECT balance FROM accounts WHERE type='Bank'")
    total = sum(r[0] for r in cur.fetchall())
    conn.close()
    return total


def bank_balance_after_months(months: int, user: str = "default") -> float:
    """Estimate bank balance after given months using current net."""
    _, _, net = calc_totals(user)
    return total_bank_balance() + net * months


def months_until_bank_negative(user: str = "default") -> int | None:
    """Return months until bank balance drops below zero if net is negative."""
    _, _, net = calc_totals(user)
    if net >= 0:
        return None
    bank = total_bank_balance()
    if bank <= 0:
        return 0
    return math.ceil(bank / -net)


def delete_category(name: str) -> None:
    """Remove a category and any associated transactions."""
    conn = get_connection()
    try:
        cur = conn.execute("SELECT id FROM categories WHERE name=?", (name,))
        row = cur.fetchone()
        if not row:
            print(f"Category '{name}' not found.")
            return
        cat_id = row[0]
        conn.execute("DELETE FROM transactions WHERE category_id=?", (cat_id,))
        conn.execute("DELETE FROM categories WHERE id=?", (cat_id,))
        conn.commit()
        print(f"Category '{name}' deleted.")
    finally:
        conn.close()


def rename_category(old_name: str, new_name: str) -> None:
    """Rename a category while preserving transactions."""
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE categories SET name=? WHERE name=?",
            (new_name, old_name),
        )
        conn.commit()
        print(f"Category '{old_name}' renamed to '{new_name}'.")
    finally:
        conn.close()


def add_user(username: str):
    """Create a new user account."""
    conn = get_connection()
    try:
        conn.execute("INSERT INTO users(username) VALUES(?)", (username,))
        conn.commit()
        print(f"User '{username}' added.")
    except sqlite3.IntegrityError:
        print(f"User '{username}' already exists.")
    finally:
        conn.close()


def set_account(
    name: str,
    balance: float,
    payment: float = 0.0,
    acct_type: str = "Other",
    apr: float = 0.0,
    escrow: float = 0.0,
    insurance: float = 0.0,
    tax: float = 0.0,
) -> None:
    """Add or update an account with details."""
    conn = get_connection()
    conn.execute(
        (
            "INSERT INTO accounts(name, balance, monthly_payment, type, apr, escrow, insurance, tax) "
            "VALUES(?,?,?,?,?,?,?,?) "
            "ON CONFLICT(name) DO UPDATE SET balance=excluded.balance, "
            "monthly_payment=excluded.monthly_payment, type=excluded.type, "
            "apr=excluded.apr, escrow=excluded.escrow, insurance=excluded.insurance, tax=excluded.tax"
        ),
        (name, balance, payment, acct_type, apr, escrow, insurance, tax),
    )
    conn.commit()
    conn.close()
    print(f"Account '{name}' set to {balance:.2f} with payment {payment:.2f}")


def delete_account(name: str) -> None:
    """Remove an account from the database."""
    conn = get_connection()
    cur = conn.execute("DELETE FROM accounts WHERE name=?", (name,))
    conn.commit()
    conn.close()
    if cur.rowcount:
        print(f"Account '{name}' deleted.")
    else:
        print(f"Account '{name}' not found.")


def list_accounts() -> None:
    """Print all account balances and payoff estimates."""
    conn = get_connection()
    cur = conn.execute(
        "SELECT name, balance, monthly_payment, type, apr, escrow, insurance, tax "
        "FROM accounts ORDER BY name"
    )
    rows = cur.fetchall()
    conn.close()
    print("Accounts:")
    for row in rows:
        months = months_to_payoff(
            row["balance"],
            row["monthly_payment"],
            row["apr"],
            row["escrow"],
            row["insurance"],
            row["tax"],
        )
        mtxt = f"{months}" if months is not None else "n/a"
        print(
            f"- {row['name']} ({row['type']}): {row['balance']:.2f} "
            f"(payment {row['monthly_payment']:.2f}, months {mtxt})"
        )
    if not rows:
        print("(none)")


def months_to_payoff(
    balance: float,
    payment: float,
    apr: float = 0.0,
    escrow: float = 0.0,
    insurance: float = 0.0,
    tax: float = 0.0,
) -> int | None:
    """Return estimated months to pay off a balance with interest."""
    balance = abs(balance)
    principal_payment = payment - escrow - insurance - tax
    if principal_payment <= 0:
        return None
    if apr <= 0:
        return int((balance + principal_payment - 1) // principal_payment)
    r = apr / 12 / 100
    if principal_payment <= balance * r:
        return None
    months = -math.log(1 - balance * r / principal_payment) / math.log(1 + r)
    return math.ceil(months)


def login_user(id_token: str) -> str | None:
    """Verify a Firebase ID token and record the user in the database."""
    if auth is None:
        print("Login failed: firebase_admin not available")
        return None
    try:
        info = auth.verify_id_token(id_token)
    except Exception as e:
        print(f"Login failed: {e}")
        return None
    uid = info.get("uid")
    phone = info.get("phone_number", uid)
    conn = get_connection()
    cur = conn.execute("SELECT username FROM users WHERE auth_uid=?", (uid,))
    row = cur.fetchone()
    if row:
        username = row[0]
    else:
        username = phone
        conn.execute(
            "INSERT INTO users(username, auth_uid) VALUES(?, ?)",
            (username, uid),
        )
        conn.commit()
    conn.close()
    print(f"Logged in as {username}")
    return username


def set_goal(category: str, amount: float, user: str = "default"):
    """Set a spending goal for a category and user."""
    conn = get_connection()
    try:
        cat_id = get_category_id(conn, category)
        user_id = get_user_id(conn, user)
        conn.execute(
            (
                "INSERT INTO goals(category_id, user_id, amount) "
                "VALUES(?,?,?) "
                "ON CONFLICT(category_id, user_id) DO UPDATE SET amount="
                "excluded.amount"
            ),
            (cat_id, user_id, amount),
        )
        conn.commit()
        print(f"Goal for {category} set to {amount:.2f} for {user}.")
    except ValueError as e:
        print(e)
    finally:
        conn.close()


def export_csv(output_file: str, user: str = "default"):
    """Export all transactions for the user to a CSV file."""
    conn = get_connection()
    user_id = get_user_id(conn, user)
    cur = conn.execute(
        """
        SELECT c.name, t.amount, t.type, t.description, t.item_name, t.created_at
        FROM transactions t
        JOIN categories c ON t.category_id = c.id
        WHERE t.user_id = ?
        ORDER BY t.created_at ASC
        """,
        (user_id,),
    )
    rows = cur.fetchall()
    with open(output_file, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(
            ["category", "amount", "type", "description", "item_name", "created_at"]
        )
        for r in rows:
            writer.writerow(r)
    print(f"Exported {len(rows)} transactions for {user} to {output_file}")


def get_category_id(conn, name: str):
    """Return the category id for the given name."""
    cur = conn.execute("SELECT id FROM categories WHERE name=?", (name,))
    row = cur.fetchone()
    if row:
        return row[0]
    raise ValueError(f"Category '{name}' not found")


def get_user_id(conn, username: str) -> int:
    """Return the user id for the given username."""
    cur = conn.execute("SELECT id FROM users WHERE username=?", (username,))
    row = cur.fetchone()
    if row:
        return row[0]
    raise ValueError(f"User '{username}' not found")


def add_transaction(
    name: str,
    amount: float,
    trans_type: str,
    description: str | None = None,
    item_name: str | None = None,
    user: str = "default",
):
    """Record an income or expense transaction."""
    conn = get_connection()
    try:
        cat_id = get_category_id(conn, name)
        user_id = get_user_id(conn, user)
        conn.execute(
            (
                "INSERT INTO transactions("
                "category_id, user_id, amount, type, description, item_name, created_at) "
                "VALUES(?,?,?,?,?,?,?)"
            ),
            (
                cat_id,
                user_id,
                amount,
                trans_type,
                description,
                item_name,
                datetime.now().isoformat(),
            ),
        )
        conn.commit()
        print(
            f"{trans_type.title()} of {amount:.2f} added to {name} for {user}."
        )
        if trans_type == "expense":
            cur = conn.execute(
                "SELECT amount FROM goals WHERE category_id=? AND user_id=?",
                (cat_id, user_id),
            )
            row = cur.fetchone()
            if row:
                goal_amount = row[0]
                cur = conn.execute(
                    (
                        "SELECT SUM(amount) FROM transactions "
                        "WHERE category_id=? AND user_id=? AND type='expense'"
                    ),
                    (cat_id, user_id),
                )
                spent = cur.fetchone()[0] or 0
                if spent > goal_amount:
                    print(
                        (
                            f"Warning: {user} exceeded goal for {name} ("
                            f"{spent:.2f}/{goal_amount:.2f})"
                        )
                    )
    except ValueError as e:
        print(e)
    finally:
        conn.close()


def category_balance(name: str, user: str = "default"):
    """Print income, expenses and balance for a single category."""
    conn = get_connection()
    try:
        cat_id = get_category_id(conn, name)
        user_id = get_user_id(conn, user)
        cur = conn.execute(
            "SELECT type, SUM(amount) AS total FROM transactions "
            "WHERE category_id=? AND user_id=? GROUP BY type",
            (cat_id, user_id),
        )
        totals = {row[0]: row[1] or 0 for row in cur.fetchall()}
        income = totals.get("income", 0)
        expense = totals.get("expense", 0)
        balance = income - expense
        print(
            (
                f"Category: {name} ({user})\n  Income: {income:.2f}"
                f"\n  Expense: {expense:.2f}\n  Balance: {balance:.2f}"
            )
        )
    except ValueError as e:
        print(e)
    finally:
        conn.close()


def show_totals(user: str = "default"):
    """Print overall income, expenses and net balance for the user."""
    income, expense, net = calc_totals(user)
    print(
        (
            f"Total Income: {income:.2f}\nTotal Expense: {expense:.2f}\n"
            f"Net Balance: {net:.2f} ({user})"
        )
    )
    warn = months_until_bank_negative(user)
    if warn is not None:
        print(f"Bank account will be negative in about {warn} months.")


def list_categories():
    """Print all available categories."""
    conn = get_connection()
    cur = conn.execute("SELECT name FROM categories ORDER BY name")
    categories = [row[0] for row in cur.fetchall()]
    print("Categories:")
    for name in categories:
        print(f"- {name}")
    if not categories:
        print("(none)")
    conn.close()


def list_transactions(category: str | None, limit: int, user: str = "default"):
    """Display recent transactions, optionally filtered by category."""
    conn = get_connection()
    try:
        user_id = get_user_id(conn, user)
        if category:
            cat_id = get_category_id(conn, category)
            cur = conn.execute(
                """
                SELECT c.name, t.amount, t.type, t.description, t.item_name, t.created_at
                FROM transactions t
                JOIN categories c ON t.category_id = c.id
                WHERE t.category_id = ? AND t.user_id = ?
                ORDER BY t.created_at DESC
                LIMIT ?
                """,
                (cat_id, user_id, limit),
            )
        else:
            cur = conn.execute(
                """
                SELECT c.name, t.amount, t.type, t.description, t.item_name, t.created_at
                FROM transactions t
                JOIN categories c ON t.category_id = c.id
                WHERE t.user_id = ?
                ORDER BY t.created_at DESC
                LIMIT ?
                """,
                (user_id, limit),
            )
        rows = cur.fetchall()
        for row in rows:
            desc = row[3] or ""
            item = row[4] or ""
            print(
                f"{row[5]} | {row[0]} | {row[2]} | {row[1]:.2f} | {item} | {desc}"
            )
        if not rows:
            print("(no transactions)")
    except ValueError as e:
        print(e)
    finally:
        conn.close()


def parse_args() -> argparse.Namespace:
    """Parse and return command line arguments."""
    parser = argparse.ArgumentParser(description="Budget Tool")
    parser.add_argument("--db", default=None, help="Path to database file")
    subparsers = parser.add_subparsers(dest="command")

    subparsers.add_parser("init", help="Initialize the database")

    parser_login = subparsers.add_parser("login", help="Login with ID token")
    parser_login.add_argument("token")

    parser_add_user = subparsers.add_parser("add-user", help="Add a user")
    parser_add_user.add_argument("username")

    parser_add_cat = subparsers.add_parser(
        "add-category", help="Add a new category"
    )
    parser_add_cat.add_argument("name")

    parser_del_cat = subparsers.add_parser(
        "delete-category", help="Delete a category"
    )
    parser_del_cat.add_argument("name")

    parser_income = subparsers.add_parser(
        "add-income", help="Add income entry"
    )
    parser_income.add_argument("category")
    parser_income.add_argument("amount", type=float)
    parser_income.add_argument("-d", "--description", default=None)
    parser_income.add_argument("-i", "--item", default=None)
    parser_income.add_argument("--user", default="default")

    parser_expense = subparsers.add_parser(
        "add-expense", help="Add expense entry"
    )
    parser_expense.add_argument("category")
    parser_expense.add_argument("amount", type=float)
    parser_expense.add_argument("-d", "--description", default=None)
    parser_expense.add_argument("-i", "--item", default=None)
    parser_expense.add_argument("--user", default="default")

    parser_balance = subparsers.add_parser(
        "balance", help="Show balance for a category"
    )
    parser_balance.add_argument("category")
    parser_balance.add_argument("--user", default="default")

    parser_totals = subparsers.add_parser("totals", help="Show overall totals")
    parser_totals.add_argument("--user", default="default")
    subparsers.add_parser("list", help="List categories")

    parser_goal = subparsers.add_parser("set-goal", help="Set budget goal")
    parser_goal.add_argument("category")
    parser_goal.add_argument("amount", type=float)
    parser_goal.add_argument("--user", default="default")

    parser_export = subparsers.add_parser(
        "export-csv", help="Export transactions to CSV"
    )
    parser_export.add_argument("--output", default="transactions.csv")
    parser_export.add_argument("--user", default="default")

    parser_acc = subparsers.add_parser(
        "set-account", help="Add or update an account balance"
    )
    parser_acc.add_argument("name")
    parser_acc.add_argument("balance", type=float)
    parser_acc.add_argument("--payment", type=float, default=0.0)

    parser_del_acc = subparsers.add_parser(
        "delete-account", help="Delete an account"
    )
    parser_del_acc.add_argument("name")

    subparsers.add_parser("list-accounts", help="List account balances")

    parser_future = subparsers.add_parser(
        "bank-balance", help="Estimate bank balance after N months"
    )
    parser_future.add_argument("months", type=int)

    parser_hist = subparsers.add_parser(
        "history", help="Show recent transactions"
    )
    parser_hist.add_argument("category", nargs="?", default=None)
    parser_hist.add_argument("--limit", type=int, default=10)
    parser_hist.add_argument("--user", default="default")

    return parser.parse_args()


def main() -> None:
    """Entry point for the command line interface."""
    global DB_FILE
    args = parse_args()
    if args.db:
        DB_FILE = Path(args.db)
    if args.command == "init":
        init_db()
        print(f"Database initialized at {DB_FILE}")
    elif args.command == "login":
        init_db()
        login_user(args.token)
    elif args.command == "add-user":
        init_db()
        add_user(args.username)
    elif args.command == "add-category":
        init_db()
        add_category(args.name)
    elif args.command == "delete-category":
        init_db()
        delete_category(args.name)
    elif args.command == "add-income":
        init_db()
        add_transaction(
            args.category, args.amount, "income", args.description, args.item, args.user
        )
    elif args.command == "add-expense":
        init_db()
        add_transaction(
            args.category, args.amount, "expense", args.description, args.item, args.user
        )
    elif args.command == "set-goal":
        init_db()
        set_goal(args.category, args.amount, args.user)
    elif args.command == "export-csv":
        init_db()
        export_csv(args.output, args.user)
    elif args.command == "balance":
        init_db()
        category_balance(args.category, args.user)
    elif args.command == "totals":
        init_db()
        show_totals(args.user)
    elif args.command == "list":
        init_db()
        list_categories()
    elif args.command == "history":
        init_db()
        list_transactions(args.category, args.limit, args.user)
    elif args.command == "set-account":
        init_db()
        set_account(args.name, args.balance, args.payment)
    elif args.command == "list-accounts":
        init_db()
        list_accounts()
    elif args.command == "bank-balance":
        init_db()
        bal = bank_balance_after_months(args.months)
        print(
            f"Estimated bank balance after {args.months} months: {bal:.2f}"
        )
    elif args.command == "delete-account":
        init_db()
        delete_account(args.name)
    else:
        print("No command provided. Use -h for help.")


if __name__ == "__main__":
    main()

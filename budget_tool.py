#!/usr/bin/env python3
"""Simple CLI-based budgeting tool using SQLite."""

import argparse
import csv
import os
import sqlite3
from urllib.parse import urlparse
from pathlib import Path
from datetime import datetime, timedelta
import math
import io
from dataclasses import dataclass
from typing import Sequence


def fmt(amount: float) -> str:
    """Return a string with thousand separators and two decimals."""
    return f"{amount:,.2f}"


try:
    import auth
except Exception:  # pragma: no cover - optional dependency
    auth = None
AUTH_ENABLED = os.environ.get("AUTH_ENABLED", "0") == "1"

DEFAULT_DB = Path(__file__).with_name("budget.db")
DB_FILE = Path(os.environ.get("BUDGET_DB", DEFAULT_DB))
SQLITE_KEY = os.environ.get("SQLITE_KEY")
DATABASE_URL = os.environ.get("DATABASE_URL")
if SQLITE_KEY:
    try:
        import pysqlcipher3.dbapi2 as sqlcipher  # type: ignore
    except Exception:  # pragma: no cover - optional dependency
        sqlcipher = None


@dataclass
class TransactionRecord:
    """Simple record for parsed statement transactions."""

    date: datetime
    description: str
    amount: float
    category: str | None = None


def parse_statement_csv(path_or_file) -> list[TransactionRecord]:
    """Parse a simple CSV bank statement and return records."""
    close = False
    if isinstance(path_or_file, (str, os.PathLike)):
        f = open(path_or_file, newline="", encoding="utf-8")
        close = True
    else:
        f = path_or_file
        if hasattr(f, "seek"):
            f.seek(0)
    try:
        sample = f.read(1024)
        if hasattr(f, "seek"):
            f.seek(0)
        try:
            dialect = csv.Sniffer().sniff(sample)
            delimiter = dialect.delimiter
        except csv.Error:
            delimiter = ","
        reader = csv.reader(f, delimiter=delimiter)
        rows = list(reader)
    finally:
        if close:
            f.close()

    if not rows:
        return []

    header = [c.lower().strip() for c in rows[0]]
    has_header = "amount" in header and "description" in header
    start = 1 if has_header else 0
    category_key = None
    if has_header:
        for h in header:
            if "category" in h:
                category_key = h
                break

    records: list[TransactionRecord] = []
    for row in rows[start:]:
        if len(row) < 3:
            continue
        if has_header:
            mapping = {header[i]: row[i] for i in range(len(header))}
            date_key = None
            for key in [
                "date",
                "posting date",
                "effective date",
                "transaction date",
            ]:
                if key in header:
                    date_key = key
                    break
            if date_key:
                date_str = mapping.get(date_key, row[0])
            else:
                date_str = row[0]
            desc = mapping.get("description", row[1])
            amt_str = mapping.get("amount", row[2])
            category = mapping.get(category_key) if category_key else None
        else:
            date_str, desc, amt_str = row[0], row[1], row[2]
            category = None
        dt = None
        for fmt in [
            lambda s: datetime.fromisoformat(s),
            lambda s: datetime.strptime(s, "%Y-%m-%d"),
            lambda s: datetime.strptime(s, "%Y%m%d"),
            lambda s: datetime.strptime(s, "%m/%d/%Y"),
        ]:
            try:
                dt = fmt(date_str)
                break
            except ValueError:
                pass
        if dt is None:
            continue
        amt = float(amt_str.replace("$", "").replace(",", ""))
        category = category.strip() if isinstance(category, str) else None
        records.append(TransactionRecord(dt, desc.strip(), amt, category))
    return records


def find_recurring_expenses(
    statements: Sequence[Sequence[TransactionRecord]],
    tolerance: float = 0.1,
    day_window: int = 0,
) -> list[tuple[str, float, str | None]]:
    """Return charges that repeat monthly with similar amount and day.

    Parameters
    ----------
    statements : Sequence[Sequence[TransactionRecord]]
        Lists of transactions grouped by month.
    tolerance : float, optional
        Allowed relative difference in amounts for a match.
    day_window : int, optional
        Accept matches that occur within this many days of the base day.
        A value of ``0`` preserves the previous exact-day behaviour.
    """
    if not statements:
        return []

    # start with the first month's transactions and look for matches
    first_month = statements[0]
    recurring: list[tuple[str, float, str | None]] = []
    seen: set[tuple[str, int]] = set()

    for base in first_month:
        key = (base.description.lower(), base.date.day)
        if key in seen:
            continue
        seen.add(key)
        amounts = [base.amount]
        for other in statements[1:]:
            match_amt = None
            for r in other:
                if (
                    r.description.lower() == base.description.lower()
                    and abs(r.date.day - base.date.day) <= day_window
                    and abs(r.amount - base.amount)
                    <= abs(base.amount) * tolerance
                ):
                    match_amt = r.amount
                    break
            if match_amt is None:
                break
            amounts.append(match_amt)
        else:  # only executed if no break occurred -> found in all months
            avg = sum(amounts) / len(amounts)
            recurring.append((base.description, abs(avg), base.category))

    return recurring


class _PGWrapper:
    """Simple wrapper to provide sqlite-like API for psycopg2 connections."""

    def __init__(self, conn):
        self._conn = conn

    def execute(self, sql, params=()):
        cur = self._conn.cursor()
        cur.execute(sql, params)
        return cur

    def commit(self):
        self._conn.commit()

    def cursor(self):
        return self._conn.cursor()

    def close(self):
        self._conn.close()


def get_connection():
    """Return a database connection using either SQLite or DATABASE_URL."""
    if DATABASE_URL:
        parsed = urlparse(DATABASE_URL)
        if parsed.scheme.startswith("postgres"):
            try:
                import psycopg2
            except Exception as exc:  # pragma: no cover - optional dependency
                raise RuntimeError("psycopg2 is required for PostgreSQL support") from exc
            conn = psycopg2.connect(DATABASE_URL)
            return _PGWrapper(conn)
        elif parsed.scheme.startswith("sqlite"):
            path = parsed.path or "budget.db"
            conn = sqlite3.connect(path)
        else:
            raise RuntimeError("Unsupported DATABASE_URL scheme")
    else:
        if SQLITE_KEY:
            if sqlcipher is None:
                raise RuntimeError("pysqlcipher3 is required for encrypted databases")
            conn = sqlcipher.connect(DB_FILE)
            conn.execute(f"PRAGMA key='{SQLITE_KEY}'")
        else:
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
    cur.execute(
        """CREATE TABLE IF NOT EXISTS monthly_expenses (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                description TEXT UNIQUE NOT NULL,
                amount REAL NOT NULL
            )"""
    )
    cur.execute(
        """CREATE TABLE IF NOT EXISTS monthly_incomes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                description TEXT UNIQUE NOT NULL,
                amount REAL NOT NULL
            )"""
    )
    cur.execute(
        """CREATE TABLE IF NOT EXISTS one_time_expenses (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                description TEXT NOT NULL,
                amount REAL NOT NULL,
                created_at TEXT NOT NULL,
                UNIQUE(description, created_at)
            )"""
    )
    cur.execute(
        """CREATE TABLE IF NOT EXISTS subscriptions (
                user_id INTEGER PRIMARY KEY,
                tier TEXT NOT NULL DEFAULT 'free' CHECK(tier IN ('free','premium')),
                start_date TEXT NOT NULL,
                last_sync TEXT,
                FOREIGN KEY(user_id) REFERENCES users(id)
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
        cur.execute("ALTER TABLE accounts ADD COLUMN type TEXT DEFAULT 'Other'")  # noqa: E501
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


def total_asset_balance() -> float:
    """Return the sum of balances for bank, crypto and stock accounts."""
    conn = get_connection()
    cur = conn.execute(
        "SELECT balance FROM accounts WHERE type IN ('Bank','Crypto Wallet','Stock Account')"  # noqa: E501
    )
    total = sum(r[0] for r in cur.fetchall())
    conn.close()
    return total


def get_all_accounts():
    """Return list of all account records."""
    conn = get_connection()
    cur = conn.execute(
        "SELECT name, balance, monthly_payment, type, apr, escrow, insurance, tax FROM accounts ORDER BY name"  # noqa: E501
    )
    rows = cur.fetchall()
    conn.close()
    return rows


def bank_balance_after_months(months: int, user: str = "default") -> float:
    """Estimate bank balance after given months using current net."""
    _, _, net = calc_totals(user)
    return total_bank_balance() + net * months


def account_balance_after_months(
    balance: float,
    payment: float,
    apr: float = 0.0,
    escrow: float = 0.0,
    insurance: float = 0.0,
    tax: float = 0.0,
    months: int = 1,
) -> float:
    """Return projected balance after a number of months."""
    rate = apr / 12 / 100
    principal_payment = payment - escrow - insurance - tax
    for _ in range(months):
        balance = balance * (1 + rate) - principal_payment
    return balance


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
            "INSERT INTO accounts(name, balance, monthly_payment, type, apr, escrow, insurance, tax) "  # noqa: E501
            "VALUES(?,?,?,?,?,?,?,?) "
            "ON CONFLICT(name) DO UPDATE SET balance=excluded.balance, "
            "monthly_payment=excluded.monthly_payment, type=excluded.type, "
            "apr=excluded.apr, escrow=excluded.escrow, insurance=excluded.insurance, tax=excluded.tax"  # noqa: E501
        ),
        (name, balance, payment, acct_type, apr, escrow, insurance, tax),
    )
    conn.commit()
    conn.close()
    print(f"Account '{name}' set to {fmt(balance)} with payment {fmt(payment)}")  # noqa: E501

    if acct_type == "Mortgage" and payment:
        try:
            add_category("Mortgage Payment")
        except Exception:
            pass
        add_transaction(
            "Mortgage Payment",
            payment,
            "expense",
            f"Payment for {name}",
        )


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
        "SELECT name, balance, monthly_payment, type, apr, escrow, insurance, tax "  # noqa: E501
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
            f"- {row['name']} ({row['type']}): {fmt(row['balance'])} "
            f"(payment {fmt(row['monthly_payment'])}, months {mtxt})"
        )
    if not rows:
        print("(none)")


def add_monthly_expense(
    desc: str, amount: float, category: str = "Misc", user: str = "default"
) -> None:
    """Insert or replace a monthly expense and create a transaction if needed."""  # noqa: E501
    amount = abs(amount)
    conn = get_connection()
    conn.execute(
        "INSERT OR REPLACE INTO monthly_expenses(description, amount) VALUES(?,?)",  # noqa: E501
        (desc, amount),
    )
    cur = conn.execute(
        "SELECT 1 FROM transactions WHERE description=?", (desc,)
    )
    exists = cur.fetchone() is not None
    conn.commit()
    conn.close()

    if not exists:
        conn = get_connection()
        cur = conn.execute("SELECT 1 FROM categories WHERE name=?", (category,))  # noqa: E501
        cat_exists = cur.fetchone() is not None
        conn.close()
        if not cat_exists:
            add_category(category)
        # ensure the user parameter is passed correctly
        add_transaction(category, amount, "expense", desc, user=user)


def get_monthly_expenses() -> list[tuple[str, float]]:
    """Return all stored monthly expenses."""
    conn = get_connection()
    cur = conn.execute(
        "SELECT description, amount FROM monthly_expenses ORDER BY description"
    )
    rows = [(r[0], r[1]) for r in cur.fetchall()]
    conn.close()
    return rows


def monthly_expense_exists(desc: str) -> bool:
    """Return True if a monthly expense with the given description exists."""
    conn = get_connection()
    cur = conn.execute(
        "SELECT 1 FROM monthly_expenses WHERE description=?", (desc,)
    )
    exists = cur.fetchone() is not None
    conn.close()
    return exists


def get_monthly_expense_amount(desc: str) -> float | None:
    """Return the amount for a specific monthly expense if present."""
    conn = get_connection()
    cur = conn.execute(
        "SELECT amount FROM monthly_expenses WHERE description=?",
        (desc,),
    )
    row = cur.fetchone()
    conn.close()
    return row[0] if row else None


def delete_monthly_expense(desc: str) -> None:
    """Delete a monthly expense and matching transactions."""
    conn = get_connection()
    conn.execute("DELETE FROM monthly_expenses WHERE description=?", (desc,))
    conn.execute("DELETE FROM transactions WHERE description=?", (desc,))
    conn.commit()
    conn.close()


def get_extra_transaction_total(user: str = "default") -> float:
    """Return the sum of extra payment transactions for a user."""
    conn = get_connection()
    user_id = get_user_id(conn, user)
    cur = conn.execute(
        "SELECT SUM(amount) FROM transactions "
        "WHERE user_id=? AND description LIKE 'Extra Payment - %'",
        (user_id,),
    )
    val = cur.fetchone()[0] or 0.0
    conn.close()
    return val


def add_monthly_income(
    desc: str, amount: float, category: str = "Misc", user: str = "default"
) -> None:
    """Insert or replace a monthly income and create a transaction if needed."""
    amount = abs(amount)
    conn = get_connection()
    conn.execute(
        "INSERT OR REPLACE INTO monthly_incomes(description, amount) VALUES(?,?)",
        (desc, amount),
    )
    cur = conn.execute(
        "SELECT 1 FROM transactions WHERE description=?", (desc,)
    )
    exists = cur.fetchone() is not None
    conn.commit()
    conn.close()

    if not exists:
        conn = get_connection()
        cur = conn.execute(
            "SELECT 1 FROM categories WHERE name=?",
            (category,),
        )
        cat_exists = cur.fetchone() is not None
        conn.close()
        if not cat_exists:
            add_category(category)
        add_transaction(category, amount, "income", desc, user=user)


def get_monthly_incomes() -> list[tuple[str, float]]:
    """Return all stored monthly incomes."""
    conn = get_connection()
    cur = conn.execute(
        "SELECT description, amount FROM monthly_incomes ORDER BY description"
    )
    rows = [(r[0], r[1]) for r in cur.fetchall()]
    conn.close()
    return rows


def delete_monthly_income(desc: str) -> None:
    """Delete a monthly income and matching transactions."""
    conn = get_connection()
    conn.execute("DELETE FROM monthly_incomes WHERE description=?", (desc,))
    conn.execute("DELETE FROM transactions WHERE description=?", (desc,))
    conn.commit()
    conn.close()


def add_one_time_expense(desc: str, amount: float, created_at: datetime) -> None:
    """Store a non-recurring expense record."""
    date_part = created_at.date().isoformat()
    conn = get_connection()
    cur = conn.execute(
        "SELECT 1 FROM one_time_expenses WHERE description=? AND amount=? "
        "AND substr(created_at,1,10)=?",
        (desc, abs(amount), date_part),
    )
    exists = cur.fetchone() is not None
    if not exists:
        conn.execute(
            "INSERT OR IGNORE INTO one_time_expenses("  # avoid duplicates
            "description, amount, created_at) VALUES(?,?,?)",
            (desc, abs(amount), created_at.isoformat()),
        )
        conn.commit()
    conn.close()


def get_one_time_expenses() -> list[tuple[int, str, float, str]]:
    """Return all one time expenses."""
    conn = get_connection()
    cur = conn.execute(
        (
            "SELECT id, description, amount, created_at "
            "FROM one_time_expenses ORDER BY created_at"
        )
    )
    rows = [(r["id"], r["description"], r["amount"], r["created_at"]) for r in cur.fetchall()]
    conn.close()
    return rows


def one_time_total() -> float:
    """Return the total amount of all one time expenses."""
    conn = get_connection()
    cur = conn.execute("SELECT SUM(amount) FROM one_time_expenses")
    total = cur.fetchone()[0] or 0.0
    conn.close()
    return total


def delete_one_time_expenses(ids: Sequence[int]) -> None:
    """Delete one time expenses by ID."""
    if not ids:
        return
    conn = get_connection()
    placeholders = ",".join("?" for _ in ids)
    conn.execute(
        f"DELETE FROM one_time_expenses WHERE id IN ({placeholders})", tuple(ids)
    )
    conn.commit()
    conn.close()


def convert_one_time_to_monthly(oid: int) -> None:
    """Convert a one time expense to a recurring monthly expense."""
    conn = get_connection()
    cur = conn.execute(
        "SELECT description, amount FROM one_time_expenses WHERE id=?",
        (oid,),
    )
    row = cur.fetchone()
    if row:
        desc, amount = row["description"], row["amount"]
        conn.execute("DELETE FROM one_time_expenses WHERE id=?", (oid,))
        conn.commit()
        conn.close()
        add_monthly_expense(desc, amount)
    else:
        conn.close()


def set_subscription(username: str, tier: str) -> None:
    """Create or update a user's subscription tier."""
    tier = tier.lower()
    if tier not in ("free", "premium"):
        raise ValueError("tier must be 'free' or 'premium'")

    conn = get_connection()
    user_id = get_user_id(conn, username)
    now = datetime.utcnow().isoformat()
    conn.execute(
        (
            "INSERT INTO subscriptions(user_id, tier, start_date) "
            "VALUES(?,?,?) ON CONFLICT(user_id) DO UPDATE SET tier=excluded.tier"
        ),
        (user_id, tier, now),
    )
    conn.commit()
    conn.close()


def get_subscription_tier(username: str) -> str:
    """Return the subscription tier for a user (defaults to 'free')."""
    conn = get_connection()
    user_id = get_user_id(conn, username)
    cur = conn.execute(
        "SELECT tier FROM subscriptions WHERE user_id=?",
        (user_id,),
    )
    row = cur.fetchone()
    conn.close()
    return row["tier"] if row else "free"


def _get_subscription_record(username: str):
    conn = get_connection()
    user_id = get_user_id(conn, username)
    cur = conn.execute(
        "SELECT tier, last_sync FROM subscriptions WHERE user_id=?",
        (user_id,),
    )
    row = cur.fetchone()
    conn.close()
    return row


def can_generate_transactions(username: str) -> bool:
    """Return True if the user may perform a transaction sync."""
    row = _get_subscription_record(username)
    if not row or row["tier"] != "premium":
        return False
    last = row["last_sync"]
    if not last:
        return True
    try:
        last_dt = datetime.fromisoformat(last)
    except ValueError:
        return True
    return datetime.utcnow() - last_dt >= timedelta(days=1)


def record_transaction_sync(username: str) -> None:
    """Update the last_sync timestamp for a user."""
    conn = get_connection()
    user_id = get_user_id(conn, username)
    conn.execute(
        "UPDATE subscriptions SET last_sync=? WHERE user_id=?",
        (datetime.utcnow().isoformat(), user_id),
    )
    conn.commit()
    conn.close()


def generate_transactions_from_plaid(username: str) -> None:
    """Fetch transactions via Plaid (placeholder)."""
    if not can_generate_transactions(username):
        raise RuntimeError("Daily transaction generation already performed")
    # TODO: Integrate with Plaid API
    print(f"Generating transactions for {username} (not yet implemented)")
    record_transaction_sync(username)


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
    months = 0
    prev = balance
    while balance > 0 and months < 10000:
        interest = balance * r
        balance = balance + interest - principal_payment
        months += 1
        if balance >= prev:
            return None
        prev = balance
    return months


def login_user(id_token: str) -> str | None:
    """Verify a Firebase ID token and record the user in the database."""
    if not AUTH_ENABLED:
        print("Authentication disabled; using default user")
        return "default"
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
        print(f"Goal for {category} set to {fmt(amount)} for {user}.")
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
        SELECT c.name, t.amount, t.type, t.description,
            t.item_name, t.created_at
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
            ["category", "amount", "type", "description", "item_name", "created_at"]  # noqa: E501
        )
        for r in rows:
            writer.writerow(r)
    print(f"Exported {len(rows)} transactions for {user} to {output_file}")


def export_csv_string(user: str = "default") -> str:
    """Return all transactions for the user as CSV text."""
    conn = get_connection()
    user_id = get_user_id(conn, user)
    cur = conn.execute(
        """
        SELECT c.name, t.amount, t.type, t.description,
            t.item_name, t.created_at
        FROM transactions t
        JOIN categories c ON t.category_id = c.id
        WHERE t.user_id = ?
        ORDER BY t.created_at ASC
        """,
        (user_id,),
    )
    rows = cur.fetchall()
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["category", "amount", "type", "description", "item_name", "created_at"])  # noqa: E501
    for r in rows:
        writer.writerow(r)
    conn.close()
    return output.getvalue()


def get_goal_status(user: str = "default") -> list[tuple[str, float, float]]:
    """Return list of (category, goal amount, spent amount) for the user."""
    conn = get_connection()
    user_id = get_user_id(conn, user)
    cur = conn.execute(
        """
        SELECT c.name, g.amount,
               (SELECT SUM(t.amount) FROM transactions t
                WHERE t.category_id = c.id AND t.user_id=? AND t.type='expense') AS spent
        FROM goals g
        JOIN categories c ON g.category_id = c.id
        WHERE g.user_id=?
        ORDER BY c.name
        """,
        (user_id, user_id),
    )
    rows = [(r[0], r[1], r[2] or 0.0) for r in cur.fetchall()]
    conn.close()
    return rows


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
    amount = abs(amount)
    conn = get_connection()
    try:
        cat_id = get_category_id(conn, name)
        user_id = get_user_id(conn, user)
        conn.execute(
            (
                "INSERT INTO transactions("
                "category_id, user_id, amount, type, description, item_name, created_at) "  # noqa: E501
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
            f"{trans_type.title()} of {fmt(amount)} added to {name} for {user}."  # noqa: E501
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
                            f"{fmt(spent)}/{fmt(goal_amount)})"
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
                f"Category: {name} ({user})\n  Income: {fmt(income)}"
                f"\n  Expense: {fmt(expense)}\n  Balance: {fmt(balance)}"
            )
        )
    except ValueError as e:
        print(e)
    finally:
        conn.close()


def show_totals(user: str = "default", months: int = 1):
    """Print income, expenses, net and account forecasts."""
    income, expense, net = calc_totals(user)
    assets = total_asset_balance()
    print(
        (
            f"Total Income: {fmt(income)}\nTotal Expense: {fmt(expense)}\n"
            f"Net Balance: {fmt(net)} ({user})\nTotal Assets: {fmt(assets)}"
        )
    )
    warn = months_until_bank_negative(user)
    if warn is not None:
        print(f"Bank account will be negative in about {warn} months.")

    accounts = get_all_accounts()
    if accounts:
        label = "month" if months == 1 else "months"
        print(f"\nAccount forecast after {months} {label}:")

        total_bank = sum(r["balance"] for r in accounts if r["type"] == "Bank")
        bank_count = sum(1 for r in accounts if r["type"] == "Bank")

        for row in accounts:
            if row["type"] == "Bank":
                share = row["balance"] / total_bank if total_bank else 1 / max(bank_count, 1)  # noqa: E501
                future = row["balance"] + net * months * share
            else:
                future = account_balance_after_months(
                    row["balance"],
                    row["monthly_payment"],
                    row["apr"],
                    row["escrow"],
                    row["insurance"],
                    row["tax"],
                    months,
                )
            change = future - row["balance"]
            sign = "+" if change >= 0 else "-"
            print(
                f"- {row['name']} ({row['type']}): {fmt(future)} "
                f"({sign}{fmt(abs(change))})"
            )


def forecast_accounts(months: int = 1) -> None:
    """Print forecasted balances for assets and liabilities."""
    accounts = get_all_accounts()
    if not accounts:
        print("No accounts")
        return

    assets: list[str] = []
    debts: list[str] = []

    total_bank = sum(r["balance"] for r in accounts if r["type"] == "Bank")
    bank_count = sum(1 for r in accounts if r["type"] == "Bank")
    _, _, net = calc_totals()

    for row in accounts:
        if row["type"] == "Bank":
            share = row["balance"] / total_bank if total_bank else 1 / max(bank_count, 1)  # noqa: E501
            future = row["balance"] + net * months * share
        else:
            future = account_balance_after_months(
                row["balance"],
                row["monthly_payment"],
                row["apr"],
                row["escrow"],
                row["insurance"],
                row["tax"],
                months,
            )
        change = future - row["balance"]
        sign = "+" if change >= 0 else "-"
        line = (
            f"- {row['name']} ({row['type']}): {fmt(future)} "
            f"({sign}{fmt(abs(change))})"
        )
        if row["type"] in ("Bank", "Crypto Wallet", "Stock Account"):
            assets.append(line)
        else:
            debts.append(line)

    label = "month" if months == 1 else "months"
    if assets:
        print(f"\nAccounts with funds after {months} {label}:")
        for line in assets:
            print(line)
    if debts:
        print(f"\nAccounts with money owed after {months} {label}:")
        for line in debts:
            print(line)


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
                SELECT c.name, t.amount, t.type, t.description,
                    t.item_name, t.created_at
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
                SELECT c.name, t.amount, t.type, t.description,
                    t.item_name, t.created_at
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
                f"{row[5]} | {row[0]} | {row[2]} | {fmt(row[1])} | {item} | {desc}"  # noqa: E501
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
    parser_totals.add_argument(
        "--months", type=int, default=1, help="Forecast account changes"
    )
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

    parser_add_mi = subparsers.add_parser(
        "add-monthly-income", help="Add recurring monthly income"
    )
    parser_add_mi.add_argument("description")
    parser_add_mi.add_argument("amount", type=float)
    parser_add_mi.add_argument("--category", default="Misc")
    parser_add_mi.add_argument("--user", default="default")

    parser_del_mi = subparsers.add_parser(
        "delete-monthly-income", help="Delete recurring monthly income"
    )
    parser_del_mi.add_argument("description")

    subparsers.add_parser("list-monthly-incomes", help="List recurring incomes")

    parser_add_me = subparsers.add_parser(
        "add-monthly-expense", help="Add recurring monthly expense"
    )
    parser_add_me.add_argument("description")
    parser_add_me.add_argument("amount", type=float)
    parser_add_me.add_argument("--category", default="Misc")

    parser_del_me = subparsers.add_parser(
        "delete-monthly-expense", help="Delete recurring monthly expense"
    )
    parser_del_me.add_argument("description")

    subparsers.add_parser("list-monthly-expenses", help="List recurring expenses")

    parser_acc = subparsers.add_parser(
        "set-account", help="Add or update an account balance"
    )
    parser_acc.add_argument("name")
    parser_acc.add_argument("balance", type=float)
    parser_acc.add_argument("--payment", type=float, default=0.0)
    parser_acc.add_argument("--type", default="Other", help="Account type")
    parser_acc.add_argument("--apr", type=float, default=0.0, help="APR percent")  # noqa: E501
    parser_acc.add_argument("--escrow", type=float, default=0.0, help="Escrow")
    parser_acc.add_argument(
        "--insurance", type=float, default=0.0, help="Home/auto insurance"
    )
    parser_acc.add_argument("--tax", type=float, default=0.0, help="Property tax")  # noqa: E501

    parser_del_acc = subparsers.add_parser(
        "delete-account", help="Delete an account"
    )
    parser_del_acc.add_argument("name")

    subparsers.add_parser("list-accounts", help="List account balances")

    parser_forecast = subparsers.add_parser(
        "forecast", help="Forecast account balances"
    )
    parser_forecast.add_argument(
        "--months", type=int, default=1, help="Number of months to forecast"
    )

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

    parser_sub = subparsers.add_parser(
        "set-subscription", help="Set subscription tier"
    )
    parser_sub.add_argument("tier", choices=["free", "premium"])
    parser_sub.add_argument("--user", default="default")

    parser_gen = subparsers.add_parser(
        "generate-transactions",
        help="Fetch transactions from Plaid (premium only)",
    )
    parser_gen.add_argument("--user", default="default")

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
            args.category, args.amount, "income", args.description, args.item, args.user  # noqa: E501
        )
    elif args.command == "add-expense":
        init_db()
        add_transaction(
            args.category, args.amount, "expense", args.description, args.item, args.user  # noqa: E501
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
        show_totals(args.user, args.months)
    elif args.command == "list":
        init_db()
        list_categories()
    elif args.command == "history":
        init_db()
        list_transactions(args.category, args.limit, args.user)
    elif args.command == "add-monthly-income":
        init_db()
        add_monthly_income(args.description, args.amount, args.category, args.user)
    elif args.command == "list-monthly-incomes":
        init_db()
        for desc, amt in get_monthly_incomes():
            print(f"- {desc}: {fmt(amt)}")
    elif args.command == "delete-monthly-income":
        init_db()
        delete_monthly_income(args.description)
    elif args.command == "add-monthly-expense":
        init_db()
        add_monthly_expense(args.description, args.amount, args.category)
    elif args.command == "list-monthly-expenses":
        init_db()
        for desc, amt in get_monthly_expenses():
            print(f"- {desc}: {fmt(amt)}")
    elif args.command == "delete-monthly-expense":
        init_db()
        delete_monthly_expense(args.description)
    elif args.command == "set-account":
        init_db()
        set_account(
            args.name,
            args.balance,
            args.payment,
            args.type,
            args.apr,
            args.escrow,
            args.insurance,
            args.tax,
        )
    elif args.command == "list-accounts":
        init_db()
        list_accounts()
    elif args.command == "forecast":
        init_db()
        forecast_accounts(args.months)
    elif args.command == "bank-balance":
        init_db()
        bal = bank_balance_after_months(args.months)
        print(
            f"Estimated bank balance after {args.months} months: {fmt(bal)}"
        )
    elif args.command == "delete-account":
        init_db()
        delete_account(args.name)
    elif args.command == "set-subscription":
        init_db()
        set_subscription(args.user, args.tier)
    elif args.command == "generate-transactions":
        init_db()
        try:
            generate_transactions_from_plaid(args.user)
        except RuntimeError as e:
            print(e)
    else:
        print("No command provided. Use -h for help.")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Simple CLI-based budgeting tool using SQLite."""

import argparse
import sqlite3
from pathlib import Path
from datetime import datetime

DB_FILE = Path(__file__).with_name("budget.db")


def get_connection():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_connection()
    cur = conn.cursor()
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
                amount REAL NOT NULL,
                type TEXT CHECK(type IN ('income','expense')) NOT NULL,
                description TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY(category_id) REFERENCES categories(id)
            )"""
    )
    conn.commit()
    conn.close()


def add_category(name: str):
    conn = get_connection()
    try:
        conn.execute("INSERT INTO categories(name) VALUES(?)", (name,))
        conn.commit()
        print(f"Category '{name}' added.")
    except sqlite3.IntegrityError:
        print(f"Category '{name}' already exists.")
    finally:
        conn.close()


def get_category_id(conn, name: str):
    cur = conn.execute("SELECT id FROM categories WHERE name=?", (name,))
    row = cur.fetchone()
    if row:
        return row[0]
    raise ValueError(f"Category '{name}' not found")


def add_transaction(name: str, amount: float, trans_type: str, description: str = None):
    conn = get_connection()
    try:
        cat_id = get_category_id(conn, name)
        conn.execute(
            "INSERT INTO transactions(category_id, amount, type, description, created_at) "
            "VALUES(?,?,?,?,?)",
            (cat_id, amount, trans_type, description, datetime.now().isoformat()),
        )
        conn.commit()
        print(f"{trans_type.title()} of {amount:.2f} added to {name}.")
    except ValueError as e:
        print(e)
    finally:
        conn.close()


def category_balance(name: str):
    conn = get_connection()
    try:
        cat_id = get_category_id(conn, name)
        cur = conn.execute(
            "SELECT type, SUM(amount) AS total FROM transactions "
            "WHERE category_id=? GROUP BY type",
            (cat_id,),
        )
        totals = {row[0]: row[1] or 0 for row in cur.fetchall()}
        income = totals.get("income", 0)
        expense = totals.get("expense", 0)
        balance = income - expense
        print(f"Category: {name}\n  Income: {income:.2f}\n  Expense: {expense:.2f}\n  Balance: {balance:.2f}")
    except ValueError as e:
        print(e)
    finally:
        conn.close()


def show_totals():
    conn = get_connection()
    cur = conn.execute(
        "SELECT type, SUM(amount) FROM transactions GROUP BY type"
    )
    totals = {row[0]: row[1] or 0 for row in cur.fetchall()}
    income = totals.get("income", 0)
    expense = totals.get("expense", 0)
    net = income - expense
    print(f"Total Income: {income:.2f}\nTotal Expense: {expense:.2f}\nNet Balance: {net:.2f}")
    conn.close()


def list_categories():
    conn = get_connection()
    cur = conn.execute("SELECT name FROM categories ORDER BY name")
    categories = [row[0] for row in cur.fetchall()]
    print("Categories:")
    for name in categories:
        print(f"- {name}")
    if not categories:
        print("(none)")
    conn.close()


def list_transactions(category: str | None, limit: int):
    """Display recent transactions, optionally filtered by category."""
    conn = get_connection()
    try:
        if category:
            cat_id = get_category_id(conn, category)
            cur = conn.execute(
                """
                SELECT c.name, t.amount, t.type, t.description, t.created_at
                FROM transactions t
                JOIN categories c ON t.category_id = c.id
                WHERE t.category_id = ?
                ORDER BY t.created_at DESC
                LIMIT ?
                """,
                (cat_id, limit),
            )
        else:
            cur = conn.execute(
                """
                SELECT c.name, t.amount, t.type, t.description, t.created_at
                FROM transactions t
                JOIN categories c ON t.category_id = c.id
                ORDER BY t.created_at DESC
                LIMIT ?
                """,
                (limit,),
            )
        rows = cur.fetchall()
        for row in rows:
            desc = row[3] or ""
            print(
                f"{row[4]} | {row[0]} | {row[2]} | {row[1]:.2f} | {desc}"
            )
        if not rows:
            print("(no transactions)")
    except ValueError as e:
        print(e)
    finally:
        conn.close()


def parse_args():
    parser = argparse.ArgumentParser(description="Budget Tool")
    subparsers = parser.add_subparsers(dest="command")

    parser_init = subparsers.add_parser("init", help="Initialize the database")

    parser_add_cat = subparsers.add_parser("add-category", help="Add a new category")
    parser_add_cat.add_argument("name")

    parser_income = subparsers.add_parser("add-income", help="Add income entry")
    parser_income.add_argument("category")
    parser_income.add_argument("amount", type=float)
    parser_income.add_argument("-d", "--description", default=None)

    parser_expense = subparsers.add_parser("add-expense", help="Add expense entry")
    parser_expense.add_argument("category")
    parser_expense.add_argument("amount", type=float)
    parser_expense.add_argument("-d", "--description", default=None)

    parser_balance = subparsers.add_parser("balance", help="Show balance for a category")
    parser_balance.add_argument("category")

    subparsers.add_parser("totals", help="Show overall totals")
    subparsers.add_parser("list", help="List categories")

    parser_hist = subparsers.add_parser(
        "history", help="Show recent transactions"
    )
    parser_hist.add_argument("category", nargs="?", default=None)
    parser_hist.add_argument("--limit", type=int, default=10)

    return parser.parse_args()


def main():
    args = parse_args()
    if args.command == "init":
        init_db()
        print(f"Database initialized at {DB_FILE}")
    elif args.command == "add-category":
        init_db()
        add_category(args.name)
    elif args.command == "add-income":
        init_db()
        add_transaction(args.category, args.amount, "income", args.description)
    elif args.command == "add-expense":
        init_db()
        add_transaction(args.category, args.amount, "expense", args.description)
    elif args.command == "balance":
        init_db()
        category_balance(args.category)
    elif args.command == "totals":
        init_db()
        show_totals()
    elif args.command == "list":
        init_db()
        list_categories()
    elif args.command == "history":
        init_db()
        list_transactions(args.category, args.limit)
    else:
        print("No command provided. Use -h for help.")


if __name__ == "__main__":
    main()

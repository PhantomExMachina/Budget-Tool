"""initial schema"""

from alembic import op
import sqlalchemy as sa

revision = '0001'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        """CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                auth_uid TEXT UNIQUE
            )"""
    )
    op.execute(
        """CREATE TABLE IF NOT EXISTS categories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE NOT NULL
            )"""
    )
    op.execute(
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
    op.execute(
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
    op.execute(
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
    op.execute(
        """CREATE TABLE IF NOT EXISTS monthly_expenses (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                description TEXT UNIQUE NOT NULL,
                amount REAL NOT NULL
            )"""
    )
    op.execute(
        """CREATE TABLE IF NOT EXISTS monthly_incomes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                description TEXT UNIQUE NOT NULL,
                amount REAL NOT NULL
            )"""
    )
    op.execute(
        """CREATE TABLE IF NOT EXISTS one_time_expenses (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                description TEXT NOT NULL,
                amount REAL NOT NULL,
                created_at TEXT NOT NULL,
                UNIQUE(description, created_at)
            )"""
    )
    op.execute(
        """CREATE TABLE IF NOT EXISTS subscriptions (
                user_id INTEGER PRIMARY KEY,
                tier TEXT NOT NULL DEFAULT 'free' CHECK(tier IN ('free','premium')),
                start_date TEXT NOT NULL,
                last_sync TEXT,
                FOREIGN KEY(user_id) REFERENCES users(id)
            )"""
    )


def downgrade():
    op.execute("DROP TABLE IF EXISTS subscriptions")
    op.execute("DROP TABLE IF EXISTS one_time_expenses")
    op.execute("DROP TABLE IF EXISTS monthly_incomes")
    op.execute("DROP TABLE IF EXISTS monthly_expenses")
    op.execute("DROP TABLE IF EXISTS accounts")
    op.execute("DROP TABLE IF EXISTS goals")
    op.execute("DROP TABLE IF EXISTS transactions")
    op.execute("DROP TABLE IF EXISTS categories")
    op.execute("DROP TABLE IF EXISTS users")


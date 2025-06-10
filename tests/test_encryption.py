import sys
from pathlib import Path
import sqlite3
import os
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import budget_tool

try:
    import pysqlcipher3
    HAS_SQLCIPHER = True
except Exception:
    HAS_SQLCIPHER = False


@pytest.mark.skipif(not HAS_SQLCIPHER, reason="pysqlcipher3 not installed")
def test_encrypted_database(tmp_path, monkeypatch):
    monkeypatch.setenv("SQLITE_KEY", "secret")
    budget_tool.DB_FILE = tmp_path / "enc.db"
    budget_tool.init_db()
    budget_tool.add_category("Food")
    conn = budget_tool.get_connection()
    conn.execute("SELECT name FROM categories")
    conn.close()
    with pytest.raises(sqlite3.DatabaseError):
        sqlite3.connect(budget_tool.DB_FILE).execute("SELECT 1")

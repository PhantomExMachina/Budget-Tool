import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import budget_tool
from datetime import datetime, timedelta


def test_set_get_subscription(tmp_path):
    budget_tool.DB_FILE = tmp_path / "budget.db"
    budget_tool.init_db()
    budget_tool.add_user("alice")

    budget_tool.set_subscription("alice", "premium")
    assert budget_tool.get_subscription_tier("alice") == "premium"

    assert budget_tool.can_generate_transactions("alice")
    budget_tool.record_transaction_sync("alice")
    assert not budget_tool.can_generate_transactions("alice")

    conn = budget_tool.get_connection()
    past = (datetime.utcnow() - timedelta(days=1, minutes=1)).isoformat()
    uid = budget_tool.get_user_id(conn, "alice")
    conn.execute("UPDATE subscriptions SET last_sync=? WHERE user_id=?", (past, uid))
    conn.commit()
    conn.close()

    assert budget_tool.can_generate_transactions("alice")

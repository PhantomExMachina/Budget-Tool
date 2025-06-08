import budget_tool
from flask import Flask, render_template, request, redirect, url_for

app = Flask(__name__)

def setup_db() -> None:
    """Initialize the database tables if they do not exist."""
    budget_tool.init_db()


def get_categories():
    conn = budget_tool.get_connection()
    cur = conn.execute("SELECT name FROM categories ORDER BY name")
    categories = [row[0] for row in cur.fetchall()]
    conn.close()
    return categories


def get_totals(user: str = "default"):
    conn = budget_tool.get_connection()
    user_id = budget_tool.get_user_id(conn, user)
    cur = conn.execute(
        "SELECT type, SUM(amount) FROM transactions WHERE user_id=? GROUP BY type",
        (user_id,),
    )
    totals = {row[0]: row[1] or 0 for row in cur.fetchall()}
    conn.close()
    income = totals.get("income", 0)
    expense = totals.get("expense", 0)
    return income, expense, income - expense


def get_accounts():
    conn = budget_tool.get_connection()
    cur = conn.execute(
        "SELECT name, balance, monthly_payment FROM accounts ORDER BY name"
    )
    rows = cur.fetchall()
    conn.close()
    data = []
    for r in rows:
        months = budget_tool.months_to_payoff(r["balance"], r["monthly_payment"])
        data.append(
            {
                "name": r["name"],
                "balance": r["balance"],
                "payment": r["monthly_payment"],
                "months": months,
            }
        )
    return data


def get_history(limit: int = 50, user: str = "default"):
    conn = budget_tool.get_connection()
    user_id = budget_tool.get_user_id(conn, user)
    cur = conn.execute(
        """
        SELECT t.id, c.name, t.amount, t.type, t.description, t.item_name, t.created_at
        FROM transactions t
        JOIN categories c ON t.category_id = c.id
        WHERE t.user_id = ?
        ORDER BY t.created_at DESC
        LIMIT ?
        """,
        (user_id, limit),
    )
    rows = cur.fetchall()
    conn.close()
    return rows


@app.route("/")
def index():
    cats = get_categories()
    income, expense, net = get_totals()
    accounts = get_accounts()
    return render_template(
        "index.html",
        categories=cats,
        income=income,
        expense=expense,
        net=net,
        accounts=accounts,
    )


@app.route("/add-category", methods=["POST"])
def add_category_route():
    name = request.form.get("name")
    if name:
        budget_tool.add_category(name)
    return redirect(url_for("index"))


@app.route("/delete-category/<name>", methods=["POST"])
def delete_category_route(name: str):
    budget_tool.delete_category(name)
    return redirect(url_for("index"))


@app.route("/add-transaction", methods=["POST"])
def add_transaction_route():
    category = request.form["category"]
    amount = request.form.get("amount", type=float)
    ttype = request.form["type"]
    desc = request.form.get("description") or None
    item = request.form.get("item_name") or None
    budget_tool.add_transaction(category, amount, ttype, desc, item)
    return redirect(url_for("index"))


@app.route("/set-account", methods=["POST"])
def set_account_route():
    name = request.form.get("name")
    balance = request.form.get("balance", type=float)
    payment = request.form.get("payment", type=float, default=0.0)
    if name and balance is not None:
        budget_tool.set_account(name, balance, payment)
    return redirect(url_for("index"))


@app.route("/history")
def history():
    rows = get_history()
    return render_template("history.html", rows=rows)


@app.route("/delete/<int:tid>", methods=["POST"])
def delete_transaction(tid: int):
    conn = budget_tool.get_connection()
    conn.execute("DELETE FROM transactions WHERE id=?", (tid,))
    conn.commit()
    conn.close()
    return redirect(url_for("history"))


def main():
    setup_db()
    app.run(debug=True)


if __name__ == "__main__":
    main()

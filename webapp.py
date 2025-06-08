import budget_tool
from flask import Flask, render_template, request, redirect, url_for

app = Flask(__name__)

@app.before_first_request
def setup_db():
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


def get_history(limit: int = 50, user: str = "default"):
    conn = budget_tool.get_connection()
    user_id = budget_tool.get_user_id(conn, user)
    cur = conn.execute(
        """
        SELECT c.name, t.amount, t.type, t.description, t.created_at
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
    return render_template(
        "index.html", categories=cats, income=income, expense=expense, net=net
    )


@app.route("/add-category", methods=["POST"])
def add_category_route():
    name = request.form.get("name")
    if name:
        budget_tool.add_category(name)
    return redirect(url_for("index"))


@app.route("/add-transaction", methods=["POST"])
def add_transaction_route():
    category = request.form["category"]
    amount = request.form.get("amount", type=float)
    ttype = request.form["type"]
    desc = request.form.get("description") or None
    budget_tool.add_transaction(category, amount, ttype, desc)
    return redirect(url_for("index"))


@app.route("/history")
def history():
    rows = get_history()
    return render_template("history.html", rows=rows)


def main():
    app.run(debug=True)


if __name__ == "__main__":
    main()

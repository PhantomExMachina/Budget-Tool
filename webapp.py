import budget_tool
from flask import Flask, render_template, request, redirect, url_for, Response

app = Flask(__name__)


@app.template_filter("fmt")
def fmt_filter(value: float) -> str:
    """Jinja filter to format numbers with commas and two decimals."""
    return budget_tool.fmt(value)

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
    """Return income, expense and net for the given user."""
    return budget_tool.calc_totals(user)


def get_accounts():
    """Return account info including payoff estimates and warnings."""
    rows = budget_tool.get_all_accounts()
    data: list[dict] = []
    warnings: list[str] = []
    for r in rows:
        months = budget_tool.months_to_payoff(
            r["balance"],
            r["monthly_payment"],
            r["apr"],
            r["escrow"],
            r["insurance"],
            r["tax"],
        )
        next_balance = budget_tool.account_balance_after_months(
            r["balance"],
            r["monthly_payment"],
            r["apr"],
            r["escrow"],
            r["insurance"],
            r["tax"],
            1,
        )
        increase = next_balance > r["balance"]
        if increase:
            warnings.append(r["name"])
        data.append(
            {
                "name": r["name"],
                "balance": r["balance"],
                "payment": r["monthly_payment"],
                "type": r["type"],
                "months": months,
                "increase": increase,
            }
        )
    return data, warnings


def get_asset_accounts():
    """Return accounts considered assets (bank, crypto and stock)."""
    rows = budget_tool.get_all_accounts()
    return [
        {"name": r["name"], "balance": r["balance"], "type": r["type"]}
        for r in rows
        if r["type"] in ("Bank", "Crypto Wallet", "Stock Account")
    ]


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


def get_goals(user: str = "default"):
    goals = []
    for name, amt, spent in budget_tool.get_goal_status(user):
        goals.append({"category": name, "goal": amt, "spent": spent})
    return goals


@app.route("/")
def index():
    cats = get_categories()
    income, expense, net = get_totals()
    accounts, warnings = get_accounts()
    assets = get_asset_accounts()
    total_assets = budget_tool.total_asset_balance()
    bank_warning = budget_tool.months_until_bank_negative()
    goals = get_goals()
    return render_template(
        "index.html",
        categories=cats,
        income=income,
        expense=expense,
        net=net,
        accounts=accounts,
        assets=assets,
        total_assets=total_assets,
        bank_warning=bank_warning,
        goals=goals,
        payment_warnings=warnings,
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


@app.route("/update-categories", methods=["POST"])
def update_categories_route():
    deletes = request.form.getlist("delete")
    for d in deletes:
        budget_tool.delete_category(d)
    for key in request.form:
        if key.startswith("old_"):
            idx = key[4:]
            old = request.form[key]
            new = request.form.get(f"name_{idx}")
            if new and old and new != old:
                budget_tool.rename_category(old, new)
    return redirect(url_for("index"))


@app.route("/update-accounts", methods=["POST"])
def update_accounts_route():
    deletes = request.form.getlist("delete")
    for d in deletes:
        budget_tool.delete_account(d)
    i = 0
    while True:
        old = request.form.get(f"old_{i}")
        if old is None:
            break
        # Skip rows marked for deletion to avoid recreating them
        if old in deletes:
            i += 1
            continue
        name = request.form.get(f"name_{i}")
        balance = request.form.get(f"balance_{i}", type=float)
        payment = request.form.get(f"payment_{i}", type=float, default=0.0)
        acct_type = request.form.get(f"type_{i}")
        if name and balance is not None:
            # Preserve APR and other fields not included in the edit table
            conn = budget_tool.get_connection()
            cur = conn.execute(
                "SELECT apr, escrow, insurance, tax FROM accounts WHERE name=?",
                (old,),
            )
            row = cur.fetchone()
            conn.close()
            if row is None:
                apr = escrow = insurance = tax = 0.0
            else:
                apr = row["apr"]
                escrow = row["escrow"]
                insurance = row["insurance"]
                tax = row["tax"]
            budget_tool.set_account(
                name, balance, payment, acct_type, apr, escrow, insurance, tax
            )
            if name != old:
                budget_tool.delete_account(old)
        i += 1
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


@app.route("/set-goal", methods=["POST"])
def set_goal_route():
    category = request.form.get("category")
    amount = request.form.get("amount", type=float)
    if category and amount is not None:
        budget_tool.set_goal(category, amount)
    return redirect(url_for("index"))


@app.route("/set-account", methods=["POST"])
def set_account_route():
    name = request.form.get("name")
    balance = request.form.get("balance", type=float)
    payment = request.form.get("payment", type=float, default=0.0)
    acct_type = request.form.get("account_type", "Other")
    apr = request.form.get("apr", type=float, default=0.0)
    escrow = request.form.get("escrow", type=float, default=0.0)
    insurance = request.form.get("insurance", type=float, default=0.0)
    tax = request.form.get("tax", type=float, default=0.0)
    if name and balance is not None:
        budget_tool.set_account(
            name, balance, payment, acct_type, apr, escrow, insurance, tax
        )
        if acct_type == "Credit Card" and payment:
            try:
                budget_tool.add_category("Credit Card Payment")
            except Exception:
                pass
            budget_tool.add_transaction(
                "Credit Card Payment", payment, "expense", f"Payment for {name}"
            )
    return redirect(url_for("index"))


@app.route("/delete-account/<name>", methods=["POST"])
def delete_account_route(name: str):
    budget_tool.delete_account(name)
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


@app.route("/export")
def export_csv_route():
    data = budget_tool.export_csv_string()
    resp = Response(data, mimetype="text/csv")
    resp.headers["Content-Disposition"] = "attachment; filename=transactions.csv"
    return resp


def main():
    setup_db()
    app.run(debug=True)


if __name__ == "__main__":
    main()

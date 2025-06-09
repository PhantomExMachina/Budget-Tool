import io
import budget_tool
import os
from typing import Any
from functools import wraps
from flask import (
    Flask,
    render_template,
    request,
    redirect,
    url_for,
    Response,
    session,
)
from flask_wtf.csrf import CSRFProtect

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "devkey")
csrf = CSRFProtect(app)
AUTH_ENABLED = os.environ.get("AUTH_ENABLED", "0") == "1"


@app.template_filter("fmt")
def fmt_filter(value: float) -> str:
    """Jinja filter to format numbers with commas and two decimals."""
    return budget_tool.fmt(value)


def require_login(func):
    """Decorator to ensure a user is logged in."""
    @wraps(func)
    def wrapper(*args, **kwargs):
        if AUTH_ENABLED and not session.get("user"):
            return redirect(url_for("login"))
        return func(*args, **kwargs)

    return wrapper


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


def get_history(
    limit: int = 50,
    user: str = "default",
    start: str | None = None,
    end: str | None = None,
):
    conn = budget_tool.get_connection()
    user_id = budget_tool.get_user_id(conn, user)
    query = (
        "SELECT t.id, c.name, t.amount, t.type, t.description, "
        "t.item_name, t.created_at FROM transactions t "
        "JOIN categories c ON t.category_id = c.id WHERE t.user_id = ?"
    )
    params: list[Any] = [user_id]
    if start:
        query += " AND t.created_at >= ?"
        params.append(start)
    if end:
        query += " AND t.created_at <= ?"
        params.append(end)
    query += " ORDER BY t.created_at DESC LIMIT ?"
    params.append(limit)
    cur = conn.execute(query, params)
    rows = cur.fetchall()
    conn.close()
    return rows


def get_expenses(limit: int = 50, user: str = "default"):
    """Return recent expense transactions."""
    conn = budget_tool.get_connection()
    user_id = budget_tool.get_user_id(conn, user)
    cur = conn.execute(
        """
        SELECT t.id, c.name, t.amount, t.type, t.description,
               t.item_name, t.created_at
        FROM transactions t
        JOIN categories c ON t.category_id = c.id
        WHERE t.user_id = ? AND t.type='expense'
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


def get_category_expenses(user: str = "default"):
    """Return total expenses per category for charts."""
    conn = budget_tool.get_connection()
    user_id = budget_tool.get_user_id(conn, user)
    cur = conn.execute(
        """
        SELECT c.name, SUM(t.amount) AS total
        FROM transactions t
        JOIN categories c ON t.category_id = c.id
        WHERE t.user_id=? AND t.type='expense'
        GROUP BY c.name
        ORDER BY total DESC
        """,
        (user_id,),
    )
    rows = [(r["name"], r["total"] or 0) for r in cur.fetchall()]
    conn.close()
    return rows


def get_account_forecast(months: int = 1):
    """Return forecasted balances for assets and debts."""
    rows = budget_tool.get_all_accounts()
    assets: list[dict] = []
    debts: list[dict] = []
    for r in rows:
        future = budget_tool.account_balance_after_months(
            r["balance"],
            r["monthly_payment"],
            r["apr"],
            r["escrow"],
            r["insurance"],
            r["tax"],
            months,
        )
        change = future - r["balance"]
        entry = {
            "name": r["name"],
            "type": r["type"],
            "future": future,
            "change": change,
        }
        if r["type"] in ("Bank", "Crypto Wallet", "Stock Account"):
            assets.append(entry)
        else:
            debts.append(entry)
    return assets, debts


@app.route("/login", methods=["GET", "POST"])
def login():
    error = None
    if not AUTH_ENABLED:
        session["user"] = "default"
        return redirect(url_for("overview"))
    if request.method == "POST":
        token = request.form.get("token", "")
        username = budget_tool.login_user(token)
        if username:
            session["user"] = username
            return redirect(url_for("overview"))
        error = "Login failed"
    return render_template("login.html", error=error)


@app.route("/logout")
def logout():
    session.pop("user", None)
    return redirect(url_for("login"))


@app.route("/")
def overview():
    income, expense, net = get_totals()
    assets = get_asset_accounts()
    expenses = get_expenses()
    return render_template(
        "overview.html",
        assets=assets,
        income=income,
        expense=expense,
        net=net,
        expenses=expenses,
    )


@app.route("/dashboard")
@require_login
def dashboard():
    income, expense, net = get_totals()
    cat_data = get_category_expenses()
    accounts, _ = get_accounts()
    acct_data = [(a["name"], a["balance"]) for a in accounts]
    return render_template(
        "dashboard.html",
        income=income,
        expense=expense,
        net=net,
        cat_data=cat_data,
        account_data=acct_data,
    )


@app.route("/manage")
@require_login
def manage():
    cats = get_categories()
    income, expense, net = get_totals()
    accounts, warnings = get_accounts()
    assets = get_asset_accounts()
    total_assets = budget_tool.total_asset_balance()
    bank_warning = budget_tool.months_until_bank_negative()
    goals = get_goals()
    incomes = budget_tool.get_monthly_incomes()
    return render_template(
        "manage.html",
        categories=cats,
        income=income,
        expense=expense,
        net=net,
        accounts=accounts,
        assets=assets,
        total_assets=total_assets,
        bank_warning=bank_warning,
        goals=goals,
        monthly_incomes=incomes,
        payment_warnings=warnings,
    )


@app.route("/forecast")
@require_login
def forecast_route():
    months = request.args.get("months", default=1, type=int)
    assets, debts = get_account_forecast(months)
    label = "month" if months == 1 else "months"
    return render_template(
        "forecast.html",
        assets=assets,
        debts=debts,
        months=months,
        label=label,
    )


@app.route("/auto-scan", methods=["GET", "POST"])
@require_login
def auto_scan():
    """Scan uploaded statements for recurring expenses."""
    results = None
    cats = get_categories()
    if request.method == "POST" and request.files:
        statements = []
        files = request.files.getlist("statement")
        for f in files:
            if not f or not f.filename:
                continue
            data = io.StringIO(f.read().decode("utf-8"))
            statements.append(budget_tool.parse_statement_csv(data))
        found = budget_tool.find_recurring_expenses(statements, day_window=2)
        existing = {d for d, _ in budget_tool.get_monthly_expenses()}
        results = [(d, a) for d, a in found if d not in existing]
        recurring_names = {d for d, _ in found}
        for month in statements:
            for r in month:
                if r.amount < 0 and r.description not in recurring_names and r.description not in existing:
                    budget_tool.add_one_time_expense(r.description, r.amount, r.date)
    elif request.method == "POST":
        i = 0
        while True:
            desc = request.form.get(f"desc_{i}")
            if desc is None:
                break
            amt = request.form.get(f"amt_{i}", type=float)
            if request.form.get(f"add_{i}") == "on":
                budget_tool.add_monthly_expense(desc, amt)
            i += 1
        results = []
    expenses = budget_tool.get_monthly_expenses()
    ones = budget_tool.get_one_time_expenses()
    one_total = budget_tool.one_time_total()
    return render_template(
        "auto_scan.html",
        results=results or [],
        categories=cats,
        monthly_expenses=expenses,
        one_time_expenses=ones,
        one_time_total=one_total,
    )  # noqa: E501


@app.route("/delete-monthly/<path:desc>", methods=["POST"])
def delete_monthly_expense_route(desc: str):
    """Remove a saved monthly expense and related transactions."""
    budget_tool.delete_monthly_expense(desc)
    return redirect(url_for("auto_scan"))


@app.route("/convert-one-time/<int:oid>", methods=["POST"])
def convert_one_time_expense(oid: int):
    """Convert a one time expense into a recurring monthly cost."""
    budget_tool.convert_one_time_to_monthly(oid)
    return redirect(url_for("auto_scan"))


@app.route("/delete-one-time", methods=["POST"])
def delete_one_time_route():
    """Delete selected one time expenses."""
    ids = [int(i) for i in request.form.getlist("delete")]
    budget_tool.delete_one_time_expenses(ids)
    return redirect(url_for("auto_scan"))


@app.route("/add-monthly-income", methods=["POST"])
@require_login
def add_monthly_income_route():
    desc = request.form.get("desc")
    amount = request.form.get("amount", type=float)
    category = request.form.get("category", "Misc")
    if desc and amount is not None:
        budget_tool.add_monthly_income(desc, amount, category)
    return redirect(url_for("manage"))


@app.route("/delete-monthly-income/<path:desc>", methods=["POST"])
@require_login
def delete_monthly_income_route(desc: str):
    budget_tool.delete_monthly_income(desc)
    return redirect(url_for("manage"))


@app.route("/add-category", methods=["POST"])
def add_category_route():
    name = request.form.get("name")
    if name:
        budget_tool.add_category(name)
    return redirect(url_for("manage"))


@app.route("/delete-category/<name>", methods=["POST"])
def delete_category_route(name: str):
    budget_tool.delete_category(name)
    return redirect(url_for("manage"))


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
    return redirect(url_for("manage"))


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
                "SELECT apr, escrow, insurance, tax FROM accounts WHERE name=?",  # noqa: E501
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
    return redirect(url_for("manage"))


@app.route("/add-transaction", methods=["POST"])
def add_transaction_route():
    category = request.form["category"]
    amount = request.form.get("amount", type=float)
    ttype = request.form["type"]
    desc = request.form.get("description") or None
    item = request.form.get("item_name") or None
    budget_tool.add_transaction(category, amount, ttype, desc, item)
    return redirect(url_for("manage"))


@app.route("/set-goal", methods=["POST"])
def set_goal_route():
    category = request.form.get("category")
    amount = request.form.get("amount", type=float)
    if category and amount is not None:
        budget_tool.set_goal(category, amount)
    return redirect(url_for("manage"))


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
                "Credit Card Payment", payment, "expense", f"Payment for {name}"  # noqa: E501
            )
    return redirect(url_for("manage"))


@app.route("/delete-account/<name>", methods=["POST"])
def delete_account_route(name: str):
    budget_tool.delete_account(name)
    return redirect(url_for("manage"))


@app.route("/history")
@require_login
def history():
    start = request.args.get("start")
    end = request.args.get("end")
    rows = get_history(start=start, end=end)
    return render_template("history.html", rows=rows)


@app.route("/delete/<int:tid>", methods=["POST"])
def delete_transaction(tid: int):
    conn = budget_tool.get_connection()
    cur = conn.execute("SELECT description FROM transactions WHERE id=?", (tid,))  # noqa: E501
    row = cur.fetchone()
    desc = row["description"] if row else None
    conn.execute("DELETE FROM transactions WHERE id=?", (tid,))
    conn.commit()
    conn.close()
    if desc:
        budget_tool.delete_monthly_expense(desc)
    return redirect(url_for("history"))


@app.route("/export")
def export_csv_route():
    data = budget_tool.export_csv_string()
    resp = Response(data, mimetype="text/csv")
    resp.headers["Content-Disposition"] = "attachment; filename=transactions.csv"  # noqa: E501
    return resp


def main():
    setup_db()
    app.run(debug=True)


if __name__ == "__main__":
    main()

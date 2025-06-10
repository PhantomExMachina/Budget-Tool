from flask import Blueprint, request, jsonify, g
import budget_tool
from functools import wraps

bp = Blueprint('api', __name__)


def token_required(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        auth = request.headers.get('Authorization', '')
        if not auth.startswith('Bearer '):
            return jsonify({'error': 'Unauthorized'}), 401
        token = auth.split(' ', 1)[1]
        user = budget_tool.login_user(token)
        if not user:
            return jsonify({'error': 'Unauthorized'}), 401
        g.current_user = user
        return func(*args, **kwargs)
    return wrapper


@bp.route('/categories', methods=['GET', 'POST'])
@token_required
def categories():
    if request.method == 'GET':
        conn = budget_tool.get_connection()
        cur = conn.execute('SELECT name FROM categories ORDER BY name')
        names = [r[0] for r in cur.fetchall()]
        conn.close()
        return jsonify(names)
    data = request.get_json() or {}
    name = data.get('name')
    if not name:
        return jsonify({'error': 'name required'}), 400
    budget_tool.add_category(name)
    return jsonify({'status': 'ok'}), 201


@bp.route('/accounts', methods=['GET', 'POST'])
@token_required
def accounts():
    if request.method == 'GET':
        rows = budget_tool.get_all_accounts()
        accounts = []
        for r in rows:
            accounts.append({
                'name': r['name'],
                'balance': r['balance'],
                'payment': r['monthly_payment'],
                'type': r['type'],
            })
        return jsonify(accounts)
    data = request.get_json() or {}
    try:
        name = data['name']
        balance = float(data['balance'])
    except Exception:
        return jsonify({'error': 'invalid data'}), 400
    payment = float(data.get('payment', 0))
    acct_type = data.get('type', 'Other')
    budget_tool.set_account(name, balance, payment, acct_type)
    return jsonify({'status': 'ok'}), 201


@bp.route('/transactions', methods=['GET', 'POST'])
@token_required
def transactions():
    user = g.current_user
    if request.method == 'GET':
        limit = request.args.get('limit', default=50, type=int)
        conn = budget_tool.get_connection()
        user_id = budget_tool.get_user_id(conn, user)
        cur = conn.execute(
            """
            SELECT t.id, c.name, t.amount, t.type, t.description,
                   t.item_name, t.created_at
            FROM transactions t
            JOIN categories c ON t.category_id = c.id
            WHERE t.user_id=?
            ORDER BY t.created_at DESC
            LIMIT ?
            """,
            (user_id, limit),
        )
        rows = cur.fetchall()
        conn.close()
        data = [
            {
                'id': r['id'],
                'category': r['name'],
                'amount': r['amount'],
                'type': r['type'],
                'description': r['description'],
                'item_name': r['item_name'],
                'created_at': r['created_at'],
            }
            for r in rows
        ]
        return jsonify(data)
    data = request.get_json() or {}
    try:
        category = data['category']
        amount = float(data['amount'])
        ttype = data['type']
    except Exception:
        return jsonify({'error': 'invalid data'}), 400
    budget_tool.add_transaction(category, amount, ttype, data.get('description'), data.get('item_name'), user=user)
    return jsonify({'status': 'ok'}), 201


@bp.route('/goals', methods=['GET', 'POST'])
@token_required
def goals():
    user = g.current_user
    if request.method == 'GET':
        rows = budget_tool.get_goal_status(user)
        data = [{'category': r[0], 'goal': r[1], 'spent': r[2]} for r in rows]
        return jsonify(data)
    data = request.get_json() or {}
    try:
        category = data['category']
        amount = float(data['amount'])
    except Exception:
        return jsonify({'error': 'invalid data'}), 400
    budget_tool.set_goal(category, amount, user)
    return jsonify({'status': 'ok'}), 201

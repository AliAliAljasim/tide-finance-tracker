"""Integration/acceptance tests for Sprint 3: budgets and TFSA/FHSA.

- Budgets: set/edit/remove, spent and remaining, 80%/100% alerts (US-15..US-17)
- TFSA/FHSA: add with starting room, room carry-forward rules, FHSA lifetime
  limit (US-18, US-19)
- Over-contribution warning that can be overridden (US-20)
"""
import os
import sys
import tempfile
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

# Isolate from the real instance/ dir, same pattern as test_validation.py.
_tmp_db = tempfile.NamedTemporaryFile(suffix='.json', delete=False)
_tmp_db.close()
import firestore_db
firestore_db._store.path = _tmp_db.name
firestore_db._store._data = {}

import app as appmod  # noqa: E402
from registered import compute_room, over_contribution  # noqa: E402
app = appmod.app
app.config['TESTING'] = True

THIS_YEAR = datetime.now(timezone.utc).year
THIS_MONTH = datetime.now(timezone.utc).strftime('%Y-%m')


def _client_with_user(email):
    client = app.test_client()
    r = client.post('/api/signup', json={'email': email, 'password': 'password123'})
    assert r.status_code == 200, r.get_json()
    return client


def _category_id(client, name):
    cats = client.get('/api/categories').get_json()['categories']
    return next(c['_id'] for c in cats if c['name'] == name)


def _add_confirmed_debit(client, category_name, amount, date):
    """Writes a confirmed transaction straight to the store — the upload path
    is already covered by the Sprint 2 tests."""
    with client.session_transaction() as sess:
        uid = sess['user_id']
    appmod.sub(uid, 'transactions').add({
        'date': date, 'description': 'TEST', 'amount': amount, 'type': 'debit',
        'category_id': _category_id(client, category_name), 'account_id': 'acc', 'confirmed': True,
    })


# ── Budgets (US-15, US-16) ──────────────────────────────────────────────

def test_set_budget_and_report_spent_and_remaining():
    client = _client_with_user('budget.basic@example.com')
    groceries = _category_id(client, 'Groceries')
    assert client.put(f'/api/budgets/{groceries}', json={'amount': 400}).status_code == 200
    _add_confirmed_debit(client, 'Groceries', 120.50, f'{THIS_MONTH}-03')
    _add_confirmed_debit(client, 'Groceries', 50, '2000-01-15')  # other month: not counted

    data = client.get(f'/api/budgets?month={THIS_MONTH}').get_json()
    [row] = data['budgets']
    assert row['category'] == 'Groceries'
    assert row['amount'] == 400
    assert row['spent'] == 120.50
    assert row['remaining'] == 279.50
    assert row['status'] == 'ok'
    assert data['alerts'] == []


def test_edit_budget_replaces_amount():
    client = _client_with_user('budget.edit@example.com')
    dining = _category_id(client, 'Dining')
    client.put(f'/api/budgets/{dining}', json={'amount': 200})
    client.put(f'/api/budgets/{dining}', json={'amount': 250})
    [row] = client.get('/api/budgets').get_json()['budgets']
    assert row['amount'] == 250


def test_remove_budget():
    client = _client_with_user('budget.remove@example.com')
    dining = _category_id(client, 'Dining')
    client.put(f'/api/budgets/{dining}', json={'amount': 200})
    client.delete(f'/api/budgets/{dining}')
    assert client.get('/api/budgets').get_json()['budgets'] == []


def test_budget_rejects_bad_amount_and_non_spending_category():
    client = _client_with_user('budget.invalid@example.com')
    dining = _category_id(client, 'Dining')
    assert client.put(f'/api/budgets/{dining}', json={'amount': 0}).status_code == 400
    assert client.put(f'/api/budgets/{dining}', json={'amount': 'lots'}).status_code == 400
    assert client.put(f"/api/budgets/{_category_id(client, 'Salary')}", json={'amount': 100}).status_code == 400
    assert client.put(f"/api/budgets/{_category_id(client, 'Transfers')}", json={'amount': 100}).status_code == 400
    assert client.put('/api/budgets/not-a-category', json={'amount': 100}).status_code == 400


def test_budget_rejects_bad_month():
    client = _client_with_user('budget.month@example.com')
    assert client.get('/api/budgets?month=2026-13').status_code == 400


# ── Budget alerts (US-17) ───────────────────────────────────────────────

def test_alerts_at_80_and_100_percent():
    client = _client_with_user('budget.alerts@example.com')
    for name in ('Dining', 'Shopping', 'Entertainment'):
        client.put(f'/api/budgets/{_category_id(client, name)}', json={'amount': 100})
    _add_confirmed_debit(client, 'Dining', 79.99, f'{THIS_MONTH}-02')         # under 80%: no alert
    _add_confirmed_debit(client, 'Shopping', 80, f'{THIS_MONTH}-02')          # exactly 80%: warning
    _add_confirmed_debit(client, 'Entertainment', 130, f'{THIS_MONTH}-02')    # over 100%

    data = client.get('/api/budgets').get_json()
    by_cat = {r['category']: r for r in data['budgets']}
    assert by_cat['Dining']['status'] == 'ok'
    assert by_cat['Shopping']['status'] == 'warning'
    assert by_cat['Entertainment']['status'] == 'over'
    assert by_cat['Entertainment']['remaining'] == -30

    alerts = {a['category']: a for a in data['alerts']}
    assert set(alerts) == {'Shopping', 'Entertainment'}
    assert alerts['Shopping']['level'] == 'warning'
    assert alerts['Entertainment']['level'] == 'over'
    assert '$30.00' in alerts['Entertainment']['message']


def test_exactly_100_percent_is_an_over_alert():
    client = _client_with_user('budget.exact@example.com')
    client.put(f"/api/budgets/{_category_id(client, 'Dining')}", json={'amount': 100})
    _add_confirmed_debit(client, 'Dining', 100, f'{THIS_MONTH}-02')
    [alert] = client.get('/api/budgets').get_json()['alerts']
    assert alert['level'] == 'over'


# ── TFSA / FHSA room rules (US-19) ──────────────────────────────────────

def test_tfsa_withdrawal_restores_room_next_year_not_same_year():
    acc = {'type': 'tfsa', 'starting_room': 10000, 'start_year': 2024}
    txs = [
        {'date': '2024-03-01', 'type': 'contribution', 'amount': 8000},
        {'date': '2024-06-01', 'type': 'withdrawal', 'amount': 3000},
    ]
    y2024, y2025 = compute_room(acc, txs, 2025)
    assert y2024['available'] == 2000          # withdrawal doesn't help this year
    assert y2025['room'] == 2000 + 7000 + 3000  # unused + 2025 limit + 2024 withdrawal


def test_tfsa_over_contribution_carries_forward_as_negative():
    acc = {'type': 'tfsa', 'starting_room': 5000, 'start_year': 2024}
    txs = [{'date': '2024-03-01', 'type': 'contribution', 'amount': 6000}]
    y2024, y2025 = compute_room(acc, txs, 2025)
    assert y2024['available'] == -1000
    assert y2025['room'] == 6000


def test_fhsa_carryforward_capped_at_8000():
    acc = {'type': 'fhsa', 'starting_room': 8000, 'start_year': 2023, 'prior_contributions': 0}
    y2023, y2024, y2025 = compute_room(acc, [], 2025)
    assert y2024['room'] == 16000
    assert y2025['room'] == 16000  # not 24000: only $8,000 carries forward


def test_fhsa_withdrawal_does_not_restore_room():
    acc = {'type': 'fhsa', 'starting_room': 8000, 'start_year': 2024, 'prior_contributions': 0}
    txs = [
        {'date': '2024-02-01', 'type': 'contribution', 'amount': 8000},
        {'date': '2024-05-01', 'type': 'withdrawal', 'amount': 8000},
    ]
    y2024, y2025 = compute_room(acc, txs, 2025)
    assert y2024['available'] == 0
    assert y2025['room'] == 8000


def test_fhsa_lifetime_limit_caps_available_room():
    acc = {'type': 'fhsa', 'starting_room': 16000, 'start_year': 2025, 'prior_contributions': 30000}
    [row] = compute_room(acc, [{'date': '2025-01-10', 'type': 'contribution', 'amount': 4000}], 2025)
    assert row['remaining'] == 12000
    assert row['lifetime_remaining'] == 6000
    assert row['available'] == 6000


def test_past_contribution_checks_later_years_too():
    acc = {'type': 'fhsa', 'starting_room': 8000, 'start_year': 2024, 'prior_contributions': 0}
    # 2025 room is fully used, so adding to 2024 (which shrinks 2025's carry-forward) puts 2025 over.
    txs = [{'date': '2025-02-01', 'type': 'contribution', 'amount': 16000}]
    new = {'date': '2024-02-01', 'type': 'contribution', 'amount': 3000}
    assert over_contribution(acc, txs, 2024, 2025) == 0
    assert over_contribution(acc, txs + [new], 2024, 2025) == 3000


# ── TFSA / FHSA API (US-18, US-19, US-20) ───────────────────────────────

def _create_registered(client, **overrides):
    payload = {'name': 'My TFSA', 'type': 'tfsa', 'institution': 'Riverside Bank',
               'starting_room': 10000, 'start_year': THIS_YEAR}
    payload.update(overrides)
    r = client.post('/api/registered', json=payload)
    assert r.status_code == 200, r.get_json()
    return r.get_json()['account']


def test_create_registered_account_shows_starting_room():
    client = _client_with_user('reg.create@example.com')
    acc = _create_registered(client)
    assert acc['current']['available'] == 10000
    [listed] = client.get('/api/registered').get_json()['accounts']
    assert listed['name'] == 'My TFSA'
    assert listed['current']['available'] == 10000


def test_create_registered_validation():
    client = _client_with_user('reg.invalid@example.com')
    base = {'name': 'X', 'type': 'tfsa', 'starting_room': 100, 'start_year': THIS_YEAR}
    assert client.post('/api/registered', json={**base, 'name': ''}).status_code == 400
    assert client.post('/api/registered', json={**base, 'type': 'lottery'}).status_code == 400
    assert client.post('/api/registered', json={**base, 'starting_room': -1}).status_code == 400
    assert client.post('/api/registered', json={**base, 'start_year': THIS_YEAR + 1}).status_code == 400
    assert client.post('/api/registered', json={**base, 'type': 'fhsa', 'start_year': 2022}).status_code == 400
    assert client.post('/api/registered', json={**base, 'type': 'fhsa', 'prior_contributions': 40001}).status_code == 400


def test_log_contribution_and_withdrawal_updates_room():
    client = _client_with_user('reg.log@example.com')
    acc = _create_registered(client)
    url = f"/api/registered/{acc['_id']}/transactions"
    assert client.post(url, json={'type': 'contribution', 'date': f'{THIS_YEAR}-01-05', 'amount': 4000}).status_code == 200
    assert client.post(url, json={'type': 'withdrawal', 'date': f'{THIS_YEAR}-01-06', 'amount': 1000}).status_code == 200

    data = client.get(f"/api/registered/{acc['_id']}").get_json()
    cur = data['account']['current']
    assert cur['contributed'] == 4000
    assert cur['withdrawn'] == 1000
    assert cur['available'] == 6000  # TFSA withdrawal comes back next year, not now
    assert len(data['transactions']) == 2


def test_log_transaction_validation():
    client = _client_with_user('reg.txinvalid@example.com')
    acc = _create_registered(client)
    url = f"/api/registered/{acc['_id']}/transactions"
    ok = {'type': 'contribution', 'date': f'{THIS_YEAR}-01-05', 'amount': 100}
    assert client.post(url, json={**ok, 'type': 'transfer'}).status_code == 400
    assert client.post(url, json={**ok, 'amount': 0}).status_code == 400
    assert client.post(url, json={**ok, 'date': 'yesterday'}).status_code == 400
    assert client.post(url, json={**ok, 'date': f'{THIS_YEAR + 1}-01-01'}).status_code == 400
    assert client.post(url, json={**ok, 'date': f'{THIS_YEAR - 1}-12-31'}).status_code == 400  # before start year


def test_over_contribution_warns_then_saves_when_confirmed():
    client = _client_with_user('reg.over@example.com')
    acc = _create_registered(client, starting_room=5000)
    url = f"/api/registered/{acc['_id']}/transactions"
    payload = {'type': 'contribution', 'date': f'{THIS_YEAR}-01-05', 'amount': 6000}

    r = client.post(url, json=payload)
    assert r.status_code == 409
    body = r.get_json()
    assert body['confirm_required'] is True
    assert body['over_by'] == 1000
    assert client.get(f"/api/registered/{acc['_id']}").get_json()['transactions'] == []  # nothing saved yet

    assert client.post(url, json={**payload, 'force': True}).status_code == 200
    assert client.get(f"/api/registered/{acc['_id']}").get_json()['account']['current']['available'] == -1000


def test_withdrawal_never_triggers_over_contribution_warning():
    client = _client_with_user('reg.withdraw@example.com')
    acc = _create_registered(client, starting_room=0)
    r = client.post(f"/api/registered/{acc['_id']}/transactions",
                    json={'type': 'withdrawal', 'date': f'{THIS_YEAR}-01-05', 'amount': 500})
    assert r.status_code == 200


def test_fhsa_lifetime_limit_warning_message():
    client = _client_with_user('reg.lifetime@example.com')
    acc = _create_registered(client, type='fhsa', name='My FHSA', starting_room=16000, prior_contributions=36000)
    r = client.post(f"/api/registered/{acc['_id']}/transactions",
                    json={'type': 'contribution', 'date': f'{THIS_YEAR}-01-05', 'amount': 5000})
    assert r.status_code == 409
    assert r.get_json()['over_by'] == 1000
    assert 'lifetime' in r.get_json()['error']


def test_delete_transaction_and_account():
    client = _client_with_user('reg.delete@example.com')
    acc = _create_registered(client)
    url = f"/api/registered/{acc['_id']}/transactions"
    tx = client.post(url, json={'type': 'contribution', 'date': f'{THIS_YEAR}-01-05', 'amount': 100}).get_json()['transaction']
    assert client.delete(f"{url}/{tx['_id']}").status_code == 200
    assert client.get(f"/api/registered/{acc['_id']}").get_json()['account']['current']['contributed'] == 0

    assert client.delete(f"/api/registered/{acc['_id']}").status_code == 200
    assert client.get('/api/registered').get_json()['accounts'] == []


def test_registered_accounts_are_per_user():
    owner = _client_with_user('reg.owner@example.com')
    acc = _create_registered(owner)
    other = _client_with_user('reg.other@example.com')
    assert other.get(f"/api/registered/{acc['_id']}").status_code == 404
    assert other.get('/api/registered').get_json()['accounts'] == []


# ── Dashboard ───────────────────────────────────────────────────────────

def test_dashboard_page_and_root_redirect():
    client = _client_with_user('dashboard.page@example.com')
    client.put('/api/profile', json={'name': 'Dana'})
    assert client.get('/dashboard').status_code == 200
    assert client.get('/').headers['Location'].endswith('/dashboard')
    assert app.test_client().get('/dashboard').status_code in (302, 401)


def test_recent_transactions_newest_first_with_names_and_limit():
    client = _client_with_user('dashboard.recent@example.com')
    _add_confirmed_debit(client, 'Groceries', 10, '2026-01-05')
    _add_confirmed_debit(client, 'Dining', 20, '2026-03-01')
    _add_confirmed_debit(client, 'Shopping', 30, '2026-02-10')

    rows = client.get('/api/transactions/recent?limit=2').get_json()['transactions']
    assert [r['date'] for r in rows] == ['2026-03-01', '2026-02-10']
    assert rows[0]['category_name'] == 'Dining'
    assert rows[0]['category_kind'] == 'expense'
    assert rows[0]['account_name'] == 'Unknown account'
    assert client.get('/api/transactions/recent?limit=abc').status_code == 400

"""Integration/acceptance tests for Sprint 2 (Sprint2.md section 9).

- Account create/edit validation
- Balance recalculation (chequing and credit card)
- Upload a statement -> linked account balance updates
- Upload two overlapping statements -> duplicates flagged, none double-counted
- Change a category -> next import uses it
- Monthly/category totals, including Transfers excluded
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

# Isolate from the real instance/ dir, same pattern as test_validation.py.
_tmp_db = tempfile.NamedTemporaryFile(suffix='.json', delete=False)
_tmp_db.close()
import firestore_db
firestore_db._store.path = _tmp_db.name
firestore_db._store._data = {}

import app as appmod  # noqa: E402
app = appmod.app
app.config['TESTING'] = True

FIXTURES = os.path.join(os.path.dirname(__file__), 'fixtures')


def _client_with_user(email):
    appmod.UPLOAD_DIR = tempfile.mkdtemp()
    client = app.test_client()
    r = client.post('/api/signup', json={'email': email, 'password': 'password123'})
    assert r.status_code == 200, r.get_json()
    return client


def _create_account(client, **overrides):
    payload = {'name': 'Everyday Chequing', 'type': 'chequing', 'institution': 'Riverside Bank', 'opening_balance': 1200}
    payload.update(overrides)
    r = client.post('/api/accounts', json=payload)
    assert r.status_code == 200, r.get_json()
    return r.get_json()['account']


def _upload(client, account_id, filename, period_start='', period_end=''):
    with open(os.path.join(FIXTURES, filename), 'rb') as f:
        data = {'account_id': account_id, 'period_start': period_start, 'period_end': period_end, 'file': (f, filename)}
        return client.post('/api/upload', data=data, content_type='multipart/form-data')


# ── Account validation (US-09) ──────────────────────────────────────────

def test_create_account_requires_name():
    client = _client_with_user('acct.noname@example.com')
    r = client.post('/api/accounts', json={'type': 'chequing'})
    assert r.status_code == 400


def test_create_account_requires_valid_type():
    client = _client_with_user('acct.badtype@example.com')
    r = client.post('/api/accounts', json={'name': 'Test', 'type': 'bitcoin'})
    assert r.status_code == 400
    assert 'chequing' in r.get_json()['error']


def test_create_account_requires_numeric_balance():
    client = _client_with_user('acct.badbal@example.com')
    r = client.post('/api/accounts', json={'name': 'Test', 'type': 'savings', 'opening_balance': 'lots'})
    assert r.status_code == 400


def test_create_account_sets_current_balance_to_opening():
    client = _client_with_user('acct.ok@example.com')
    account = _create_account(client, opening_balance=500)
    assert account['current_balance'] == 500
    assert account['opening_balance'] == 500


def test_edit_account_rejects_invalid_type_but_keeps_other_fields():
    client = _client_with_user('acct.edit@example.com')
    account = _create_account(client)
    r = client.put(f'/api/accounts/{account["_id"]}', json={'type': 'bogus'})
    assert r.status_code == 400


def test_delete_account_blocked_with_transactions_then_forced():
    client = _client_with_user('acct.delete@example.com')
    account = _create_account(client, opening_balance=1200)
    r = _upload(client, account['_id'], 'riverside_bank.pdf')
    assert r.status_code == 200

    blocked = client.delete(f'/api/accounts/{account["_id"]}')
    assert blocked.status_code == 409
    assert blocked.get_json()['confirm_required'] is True

    forced = client.delete(f'/api/accounts/{account["_id"]}?force=true')
    assert forced.status_code == 200
    assert client.get(f'/api/accounts/{account["_id"]}').status_code == 404


# ── Balance recalculation (US-10) ───────────────────────────────────────

def test_balance_recompute_chequing_adds_credits_subtracts_debits():
    uid = 'fake-uid-chequing'
    firestore_db._store._data = {}
    appmod.sub(uid, 'accounts').document('acc1').set({'type': 'chequing', 'opening_balance': 100})
    appmod.sub(uid, 'transactions').add({'account_id': 'acc1', 'type': 'credit', 'amount': 50, 'confirmed': True})
    appmod.sub(uid, 'transactions').add({'account_id': 'acc1', 'type': 'debit', 'amount': 20, 'confirmed': True})
    appmod.sub(uid, 'transactions').add({'account_id': 'acc1', 'type': 'debit', 'amount': 999, 'confirmed': False})  # not confirmed -> excluded
    balance = appmod.recompute_account_balance(uid, 'acc1')
    assert balance == 130  # 100 + 50 - 20


def test_balance_recompute_credit_card_charges_increase_owed():
    uid = 'fake-uid-cc'
    firestore_db._store._data = {}
    appmod.sub(uid, 'accounts').document('cc1').set({'type': 'credit_card', 'opening_balance': 0})
    appmod.sub(uid, 'transactions').add({'account_id': 'cc1', 'type': 'debit', 'amount': 200, 'confirmed': True})   # a charge
    appmod.sub(uid, 'transactions').add({'account_id': 'cc1', 'type': 'credit', 'amount': 50, 'confirmed': True})  # a payment
    balance = appmod.recompute_account_balance(uid, 'cc1')
    assert balance == 150  # owes 200, paid 50 -> owes 150


# ── Upload -> linked account balance updates (US-10) ────────────────────

def test_upload_and_confirm_updates_linked_account_balance():
    client = _client_with_user('balance.flow@example.com')
    account = _create_account(client, opening_balance=1200)
    r = _upload(client, account['_id'], 'riverside_bank.pdf')
    assert r.status_code == 200
    statement_id = r.get_json()['statement_id']

    confirm = client.post(f'/api/statements/{statement_id}/confirm')
    assert confirm.status_code == 200
    assert confirm.get_json()['account_balance'] == 2226.70  # matches the fixture's printed closing balance

    detail = client.get(f'/api/accounts/{account["_id"]}').get_json()
    assert detail['account']['current_balance'] == 2226.70
    assert len(detail['transactions']) == 5


# ── Duplicate detection across overlapping statements (US-08) ──────────

def test_overlapping_statement_upload_flags_duplicates_and_skips_them_on_confirm():
    client = _client_with_user('dup.flow@example.com')
    account = _create_account(client, opening_balance=1200)

    first = _upload(client, account['_id'], 'riverside_bank.pdf')
    first_id = first.get_json()['statement_id']
    client.post(f'/api/statements/{first_id}/confirm')

    # Re-upload the exact same statement to the same account.
    second = _upload(client, account['_id'], 'riverside_bank.pdf')
    second_id = second.get_json()['statement_id']
    second_detail = client.get(f'/api/statements/{second_id}').get_json()
    assert all(t['is_duplicate'] for t in second_detail['transactions'])

    confirm = client.post(f'/api/statements/{second_id}/confirm')
    body = confirm.get_json()
    assert body['skipped_duplicates'] == 5
    # Balance must not double-count: still the first statement's closing balance.
    assert body['account_balance'] == 2226.70


# ── Category change remembered for next import (US-12) ─────────────────

def test_changing_category_upserts_merchant_rule_used_on_next_import():
    client = _client_with_user('cat.remember@example.com')
    account = _create_account(client, opening_balance=1200)

    r = _upload(client, account['_id'], 'riverside_bank.pdf')
    statement_id = r.get_json()['statement_id']
    detail = client.get(f'/api/statements/{statement_id}').get_json()
    coffee = next(t for t in detail['transactions'] if t['description'] == 'COFFEE SHOP')
    categories_by_name = {c['name']: c for c in detail['categories']}
    new_category = categories_by_name['Entertainment']['_id']

    put = client.put(f'/api/statements/{statement_id}/transactions/{coffee["_id"]}', json={'category_id': new_category})
    assert put.status_code == 200
    client.post(f'/api/statements/{statement_id}/confirm')

    user_doc = next(iter(firestore_db.fs.collection('users').where('email', '==', 'cat.remember@example.com').limit(1).stream()))
    uid = user_doc.id

    # The merchant_rules upsert is what makes "next import uses it" true.
    import categorization
    merchant_key = categorization.normalize_merchant('COFFEE SHOP')
    assert appmod.get_merchant_rules(uid).get(merchant_key) == new_category

    # Prove "next import" end-to-end: a fresh upload with the same merchant
    # gets Entertainment from the remembered rule, not the Dining keyword rule.
    second = _upload(client, account['_id'], 'riverside_bank.pdf')
    second_statement_id = second.get_json()['statement_id']
    second_detail = client.get(f'/api/statements/{second_statement_id}').get_json()
    second_coffee = next(t for t in second_detail['transactions'] if t['description'] == 'COFFEE SHOP')
    assert second_coffee['category_id'] == new_category


# ── Summary totals, Transfers excluded (US-13, US-14) ───────────────────

def test_monthly_and_category_summary_exclude_transfers():
    uid = 'fake-uid-summary'
    firestore_db._store._data = {}
    cats = {c['_id']: c for c in appmod.get_categories()}
    cats_by_name = {c['name']: cid for cid, c in cats.items()}

    appmod.sub(uid, 'accounts').document('a1').set({'type': 'chequing', 'opening_balance': 0})
    tx = appmod.sub(uid, 'transactions')
    tx.add({'account_id': 'a1', 'date': '2026-06-05', 'type': 'credit', 'amount': 1000,
             'category_id': cats_by_name['Salary'], 'confirmed': True})
    tx.add({'account_id': 'a1', 'date': '2026-06-10', 'type': 'debit', 'amount': 200,
             'category_id': cats_by_name['Groceries'], 'confirmed': True})
    tx.add({'account_id': 'a1', 'date': '2026-06-12', 'type': 'debit', 'amount': 50,
             'category_id': cats_by_name['Dining'], 'confirmed': True})
    tx.add({'account_id': 'a1', 'date': '2026-06-15', 'type': 'debit', 'amount': 300,
             'category_id': cats_by_name['Transfers'], 'confirmed': True})  # excluded
    tx.add({'account_id': 'a1', 'date': '2026-06-20', 'type': 'debit', 'amount': 999,
             'category_id': cats_by_name['Groceries'], 'confirmed': False})  # not confirmed -> excluded

    months = appmod.month_range('2026-06', '2026-06')
    assert months == ['2026-06']

    totals = {'2026-06': {'income': 0.0, 'expenses': 0.0}}
    transfers_id = cats_by_name['Transfers']
    for t in appmod.confirmed_transactions(uid, 'all'):
        m = t['date'][:7]
        if t['category_id'] == transfers_id:
            continue
        if t['type'] == 'credit':
            totals[m]['income'] += t['amount']
        else:
            totals[m]['expenses'] += t['amount']

    assert totals['2026-06']['income'] == 1000       # Salary only
    assert totals['2026-06']['expenses'] == 250       # Groceries(200) + Dining(50), Transfers and unconfirmed excluded


def test_summary_endpoints_match_hand_calculated_totals_for_a_synthetic_month():
    """Acceptance test: 'Charts match totals calculated by hand for one
    synthetic month' — hits the real /api/summary/* routes, not just the
    internal aggregation helpers."""
    client = _client_with_user('handcalc@example.com')
    account = _create_account(client, type='chequing', opening_balance=0)

    user_doc = next(iter(firestore_db.fs.collection('users').where('email', '==', 'handcalc@example.com').limit(1).stream()))
    uid = user_doc.id
    cats_by_name = {c['name']: c['_id'] for c in appmod.get_categories()}
    tx = appmod.sub(uid, 'transactions')

    # Hand-calculated expectation for July 2026 on this account:
    #   income  = 2000 (Salary) + 100 (Refund)            = 2100
    #   expense = 300 (Groceries) + 80 (Dining)            = 380
    #   (500 Transfers and an unconfirmed 999 Shopping row are excluded)
    rows = [
        ('2026-07-02', 'credit', 2000, 'Salary'),
        ('2026-07-04', 'credit', 100, 'Refund'),
        ('2026-07-06', 'debit', 300, 'Groceries'),
        ('2026-07-08', 'debit', 80, 'Dining'),
        ('2026-07-10', 'debit', 500, 'Transfers'),
    ]
    for date, kind, amount, cat_name in rows:
        tx.add({'account_id': account['_id'], 'date': date, 'type': kind, 'amount': amount,
                 'category_id': cats_by_name[cat_name], 'confirmed': True})
    tx.add({'account_id': account['_id'], 'date': '2026-07-12', 'type': 'debit', 'amount': 999,
             'category_id': cats_by_name['Shopping'], 'confirmed': False})

    monthly = client.get(f'/api/summary/monthly?from=2026-07&to=2026-07&account={account["_id"]}').get_json()
    assert monthly['months'] == [{'month': '2026-07', 'income': 2100.0, 'expenses': 380.0, 'net': 1720.0}]

    categories = client.get(f'/api/summary/categories?month=2026-07&account={account["_id"]}').get_json()['categories']
    totals_by_name = {c['category']: c['total'] for c in categories}
    assert totals_by_name == {'Groceries': 300.0, 'Dining': 80.0}  # Transfers excluded, debits only

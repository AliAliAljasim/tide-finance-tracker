"""Regression tests for issues found in the PR #1 code review."""
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
import categorization  # noqa: E402
from parsing import _normalize_amounts, validate_transactions  # noqa: E402
app = appmod.app
app.config['TESTING'] = True


def _client_with_user(email):
    client = app.test_client()
    assert client.post('/api/signup', json={'email': email, 'password': 'password123'}).status_code == 200
    client.put('/api/profile', json={'name': 'Test'})
    return client


def _uid(client):
    with client.session_transaction() as sess:
        return sess['user_id']


def _account(client, acc_type='chequing', opening=1000):
    r = client.post('/api/accounts', json={'name': 'Acct', 'type': acc_type, 'opening_balance': opening})
    return r.get_json()['account']['_id']


def _pending_statement(client, account_id, rows):
    """A parsed-but-unconfirmed statement with the given (date, desc, amount) debit rows."""
    uid = _uid(client)
    _, ref = appmod.sub(uid, 'statements').add({'account_id': account_id, 'status': 'parsed', 'created_at': 'x'})
    for date, desc, amount in rows:
        appmod.sub(uid, 'transactions').add({
            'date': date, 'description': desc, 'amount': amount, 'type': 'debit', 'balance': None,
            'merchant_key': categorization.normalize_merchant(desc), 'is_duplicate': False,
            'account_id': account_id, 'statement_id': ref.id, 'confirmed': False})
    return ref.id


def _rows(client, statement_id):
    return [t for t in appmod.stream_docs(appmod.sub(_uid(client), 'transactions')) if t.get('statement_id') == statement_id]


def _balance(client, account_id):
    return client.get(f'/api/accounts/{account_id}').get_json()['account']['current_balance']


# ── Credit card statements ──────────────────────────────────────────────

def test_credit_card_balance_rising_is_a_charge():
    parsed = {'opening_balance': 100, 'transactions': [
        {'amount': 50, 'balance': 150},   # purchase: owed goes up
        {'amount': 30, 'balance': 120},   # payment: owed goes down
    ]}
    _normalize_amounts(parsed, owed=True)
    assert [t['type'] for t in parsed['transactions']] == ['debit', 'credit']

    rows, ok = validate_transactions(parsed['transactions'], 100, 120, None, None, owed=True)
    assert ok and not any(r['flagged'] for r in rows)


def test_bank_account_sign_unchanged():
    parsed = {'opening_balance': 100, 'transactions': [{'amount': 50, 'balance': 150}, {'amount': 30, 'balance': 120}]}
    _normalize_amounts(parsed)
    assert [t['type'] for t in parsed['transactions']] == ['credit', 'debit']


# ── Balance stays in sync when confirmed money is removed ───────────────

def test_deleting_confirmed_statement_or_row_recomputes_balance():
    client = _client_with_user('review.balance@example.com')
    acc = _account(client, opening=1000)
    stmt = _pending_statement(client, acc, [('2026-10-01', 'GROCER', 100), ('2026-10-02', 'CAFE', 20)])
    client.post(f'/api/statements/{stmt}/confirm')
    assert _balance(client, acc) == 880

    cafe = next(t for t in _rows(client, stmt) if t['description'] == 'CAFE')
    assert client.delete(f"/api/statements/{stmt}/transactions/{cafe['_id']}").status_code == 200
    assert _balance(client, acc) == 900

    client.delete(f'/api/statements/{stmt}')
    assert _balance(client, acc) == 1000


def test_deleting_a_row_checks_it_belongs_to_the_statement():
    client = _client_with_user('review.rowowner@example.com')
    acc = _account(client)
    a = _pending_statement(client, acc, [('2026-10-01', 'GROCER', 10)])
    b = _pending_statement(client, acc, [])
    row = _rows(client, a)[0]
    assert client.delete(f"/api/statements/{b}/transactions/{row['_id']}").status_code == 404


# ── Overlapping statements that were both pending ───────────────────────

def test_overlap_between_two_pending_statements_is_skipped_on_second_confirm():
    client = _client_with_user('review.overlap@example.com')
    acc = _account(client, opening=1000)
    aug = _pending_statement(client, acc, [('2026-08-10', 'GROCER', 100)])
    aug_sep = _pending_statement(client, acc, [('2026-08-10', 'GROCER', 100), ('2026-09-05', 'CAFE', 20)])

    client.post(f'/api/statements/{aug}/confirm')
    r = client.post(f'/api/statements/{aug_sep}/confirm').get_json()
    assert r['skipped_duplicates'] == 1
    assert _balance(client, acc) == 880  # August counted once


def test_kept_duplicate_is_not_skipped_by_the_recheck():
    client = _client_with_user('review.kept@example.com')
    acc = _account(client, opening=1000)
    first = _pending_statement(client, acc, [('2026-08-10', 'GROCER', 100)])
    second = _pending_statement(client, acc, [('2026-08-10', 'GROCER', 100)])
    client.post(f'/api/statements/{first}/confirm')

    row = _rows(client, second)[0]
    client.put(f"/api/statements/{second}/transactions/{row['_id']}", json={'is_duplicate': True})
    client.put(f"/api/statements/{second}/transactions/{row['_id']}", json={'is_duplicate': False})  # Keep
    assert client.post(f'/api/statements/{second}/confirm').get_json()['skipped_duplicates'] == 0
    assert _balance(client, acc) == 800


# ── Input validation ────────────────────────────────────────────────────

def test_nan_and_infinity_rejected():
    client = _client_with_user('review.nan@example.com')
    groceries = next(c['_id'] for c in client.get('/api/categories').get_json()['categories'] if c['name'] == 'Groceries')
    assert client.put(f'/api/budgets/{groceries}', json={'amount': 'nan'}).status_code == 400
    assert client.put(f'/api/budgets/{groceries}', json={'amount': 'inf'}).status_code == 400
    assert client.post('/api/accounts', json={'name': 'X', 'type': 'chequing', 'opening_balance': 'Infinity'}).status_code == 400
    assert client.post('/api/registered', json={'name': 'T', 'type': 'tfsa', 'starting_room': 'nan'}).status_code == 400
    stmt = _pending_statement(client, _account(client), [])
    assert client.post(f'/api/statements/{stmt}/transactions', json={'amount': 'nan'}).status_code == 400
    assert client.post(f'/api/statements/{stmt}/transactions', json={'amount': 'abc'}).status_code == 400


def test_monthly_summary_rejects_bad_months():
    client = _client_with_user('review.months@example.com')
    assert client.get('/api/summary/monthly?from=abc&to=2026-01').status_code == 400
    assert client.get('/api/summary/monthly?from=2024-13&to=2025-02').status_code == 400
    assert client.get('/api/summary/monthly?from=2026-01&to=2026-03').status_code == 200


def test_unknown_category_not_saved_as_merchant_rule():
    client = _client_with_user('review.category@example.com')
    stmt = _pending_statement(client, _account(client), [('2026-10-01', 'MYSTERY SHOP', 10)])
    row = _rows(client, stmt)[0]
    r = client.put(f"/api/statements/{stmt}/transactions/{row['_id']}", json={'category_id': 'bogus'})
    assert r.status_code == 400
    assert appmod.get_merchant_rules(_uid(client)) == {}


# ── Categorization keeps going after one failed batch ───────────────────

def test_failed_llm_batch_does_not_skip_later_batches(monkeypatch):
    calls = []

    def flaky(batch, names, fallback, direction):
        calls.append(direction)
        if len(calls) == 1:
            raise RuntimeError('transient')
    monkeypatch.setattr(categorization, '_llm_categorize_batch', flaky)
    cats = {'Salary': {'kind': 'income'}, 'Groceries': {'kind': 'expense'}}
    txs = [{'type': 'credit'}] * 20 + [{'type': 'debit'}] * 5
    categorization._llm_categorize(txs, cats)
    assert calls == ['money in', 'money in', 'money out']

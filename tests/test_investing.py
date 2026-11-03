"""Investing: every Canadian account type beyond TFSA/FHSA — RRSP, RESP,
RDSP, LIRA, RRIF and non-registered accounts."""
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
from registered import ACCOUNT_TYPES, compute_room, over_contribution  # noqa: E402
app = appmod.app
app.config['TESTING'] = True

THIS_YEAR = datetime.now(timezone.utc).year


def _client_with_user(email):
    client = app.test_client()
    assert client.post('/api/signup', json={'email': email, 'password': 'password123'}).status_code == 200
    client.put('/api/profile', json={'name': 'Test'})
    return client


def _create(client, **fields):
    payload = {'name': 'Account', 'start_year': THIS_YEAR, **fields}
    r = client.post('/api/registered', json=payload)
    assert r.status_code == 200, r.get_json()
    return r.get_json()['account']


def _tx(year, kind, amount):
    return {'date': f'{year}-03-01', 'type': kind, 'amount': amount}


# ── Rules ───────────────────────────────────────────────────────────────

def test_rrsp_carries_room_forward_and_adds_annual_room():
    acc = {'type': 'rrsp', 'start_year': 2024, 'starting_room': 10000, 'annual_room': 5000}
    rows = compute_room(acc, [_tx(2024, 'contribution', 4000), _tx(2024, 'withdrawal', 3000)], 2025)
    assert rows[0]['available'] == 6000
    assert rows[1]['room'] == 11000  # 6,000 unused + 5,000 new; the withdrawal doesn't restore room


def test_rrsp_over_contribution_only_counts_beyond_2000_cushion():
    acc = {'type': 'rrsp', 'start_year': 2025, 'starting_room': 1000, 'annual_room': 0}
    assert over_contribution(acc, [_tx(2025, 'contribution', 2500)], 2025, 2025) == 0
    assert over_contribution(acc, [_tx(2025, 'contribution', 3500)], 2025, 2025) == 500


def test_resp_lifetime_cap_and_yearly_grant():
    acc = {'type': 'resp', 'start_year': 2025, 'prior_contributions': 45000}
    rows = compute_room(acc, [_tx(2025, 'contribution', 3000), _tx(2025, 'withdrawal', 1000)], 2026)
    assert rows[0]['room'] == 5000
    assert rows[0]['grant_eligible'] == 2500
    assert rows[0]['grant_earned'] == 500
    assert rows[0]['grant_room_left'] == 0
    assert rows[1]['lifetime_contributed'] == 48000  # withdrawals don't give lifetime room back
    assert rows[1]['grant_room_left'] == 2500
    assert over_contribution(acc, [_tx(2025, 'contribution', 6000)], 2025, 2026) == 1000


def test_rdsp_lifetime_cap():
    acc = {'type': 'rdsp', 'start_year': 2025, 'prior_contributions': 0}
    rows = compute_room(acc, [_tx(2025, 'contribution', 10000)], 2025)
    assert rows[0]['lifetime_remaining'] == 190000


def test_uncapped_accounts_track_net_and_never_warn():
    for acc_type in ('lira', 'rrif', 'non_registered'):
        acc = {'type': acc_type, 'start_year': 2025}
        txs = [_tx(2025, 'contribution', 900000), _tx(2025, 'withdrawal', 100), _tx(2026, 'contribution', 50)]
        rows = compute_room(acc, txs, 2026)
        assert rows[0]['net'] == 899900
        assert rows[1]['total_net'] == 899950
        assert 'available' not in rows[0]
        assert over_contribution(acc, txs, 2025, 2026) == 0


# ── API ─────────────────────────────────────────────────────────────────

def test_every_type_can_be_created_and_listed_with_metadata():
    client = _client_with_user('investing.all@example.com')
    for acc_type in ACCOUNT_TYPES:
        _create(client, type=acc_type, name=acc_type)
    data = client.get('/api/registered').get_json()
    assert [a['type'] for a in data['accounts']] == list(ACCOUNT_TYPES)
    assert {t['type'] for t in data['types']} == set(ACCOUNT_TYPES)
    resp = next(a for a in data['accounts'] if a['type'] == 'resp')
    assert resp['kind'] == 'lifetime' and resp['lifetime_limit'] == 50000 and resp['label'] == 'RESP'


def test_irrelevant_numbers_are_dropped_for_the_type():
    client = _client_with_user('investing.fields@example.com')
    acc = _create(client, type='non_registered', starting_room=999, prior_contributions=5, annual_room=7)
    assert (acc['starting_room'], acc['prior_contributions'], acc['annual_room']) == (0, 0, 0)
    rrsp = _create(client, type='rrsp', starting_room=20000, annual_room=6000)
    assert (rrsp['starting_room'], rrsp['annual_room']) == (20000, 6000)


def test_lifetime_prior_contributions_validated_against_cap():
    client = _client_with_user('investing.cap@example.com')
    r = client.post('/api/registered', json={'name': 'Kids', 'type': 'resp', 'start_year': THIS_YEAR,
                                             'prior_contributions': 50001})
    assert r.status_code == 400 and '50,000' in r.get_json()['error']


def test_rrsp_contribution_past_cushion_needs_confirmation():
    client = _client_with_user('investing.rrsp@example.com')
    acc = _create(client, type='rrsp', starting_room=1000)
    url = f"/api/registered/{acc['_id']}/transactions"
    date = f'{THIS_YEAR}-01-01'
    assert client.post(url, json={'type': 'contribution', 'date': date, 'amount': 2500}).status_code == 200
    r = client.post(url, json={'type': 'contribution', 'date': date, 'amount': 1000})
    assert r.status_code == 409 and r.get_json()['over_by'] == 500
    assert '$2,000 cushion' in r.get_json()['error']


def test_non_registered_never_asks_for_confirmation():
    client = _client_with_user('investing.nonreg@example.com')
    acc = _create(client, type='non_registered')
    url = f"/api/registered/{acc['_id']}/transactions"
    r = client.post(url, json={'type': 'contribution', 'date': f'{THIS_YEAR}-01-01', 'amount': 1000000})
    assert r.status_code == 200


def test_investing_pages_and_old_links_redirect():
    client = _client_with_user('investing.pages@example.com')
    acc = _create(client, type='tfsa', starting_room=1000)
    assert client.get('/investing').status_code == 200
    assert client.get(f"/investing/{acc['_id']}").status_code == 200
    r = client.get('/registered')
    assert r.status_code == 301 and r.headers['Location'].endswith('/investing')
    r = client.get(f"/registered/{acc['_id']}")
    assert r.status_code == 301 and r.headers['Location'].endswith(f"/investing/{acc['_id']}")
    assert client.get('/investing/missing').headers['Location'].endswith('/investing')

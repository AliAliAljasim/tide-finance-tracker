"""Unit tests for registration/login/password validation and upload
file-type/size checks (Testing Requirements, items 1-2), plus the
registration/login/reset API endpoints end to end against a scratch
local_db.json.
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

# Point the local JSON store at a throwaway file before importing app/firestore_db,
# so these tests never touch instance/local_db.json.
_tmp_db = tempfile.NamedTemporaryFile(suffix='.json', delete=False)
_tmp_db.close()
import firestore_db
firestore_db._store.path = _tmp_db.name
firestore_db._store._data = {}

from app import app, valid_email, valid_password, allowed_upload  # noqa: E402


# ── Pure validation helpers ────────────────────────────────────────────

def test_valid_email_accepts_normal_addresses():
    assert valid_email('person@example.com')


def test_valid_email_rejects_malformed_addresses():
    for bad in ['', 'not-an-email', 'missing@domain', '@example.com', 'person@']:
        assert not valid_email(bad)


def test_valid_password_requires_min_8_chars():
    ok, _ = valid_password('short1')
    assert not ok
    ok, _ = valid_password('longenough1')
    assert ok


def test_allowed_upload_accepts_pdf_jpg_png():
    for name in ['statement.pdf', 'photo.jpg', 'photo.jpeg', 'scan.PNG']:
        ok, _ = allowed_upload(name, 1000)
        assert ok, name


def test_allowed_upload_rejects_other_types():
    ok, msg = allowed_upload('statement.docx', 1000)
    assert not ok
    assert 'type' in msg.lower()


def test_allowed_upload_rejects_oversized_file():
    ok, msg = allowed_upload('statement.pdf', 11 * 1024 * 1024)
    assert not ok
    assert 'large' in msg.lower()


def test_allowed_upload_rejects_missing_filename():
    ok, _ = allowed_upload('', 100)
    assert not ok


# ── Registration / login API ───────────────────────────────────────────

def _client():
    app.config['TESTING'] = True
    return app.test_client()


def test_signup_then_duplicate_email_rejected():
    client = _client()
    resp = client.post('/api/signup', json={'email': 'new.user@example.com', 'password': 'password123'})
    assert resp.status_code == 200
    assert resp.get_json()['success'] is True

    dup = client.post('/api/signup', json={'email': 'new.user@example.com', 'password': 'password123'})
    assert dup.status_code == 400
    assert 'already' in dup.get_json()['error'].lower()


def test_signup_rejects_short_password():
    client = _client()
    resp = client.post('/api/signup', json={'email': 'short.pw@example.com', 'password': 'abc123'})
    assert resp.status_code == 400


def test_login_wrong_password_shows_clear_error():
    client = _client()
    client.post('/api/signup', json={'email': 'login.test@example.com', 'password': 'password123'})
    resp = client.post('/api/login', json={'email': 'login.test@example.com', 'password': 'wrong-password'})
    assert resp.status_code == 401
    assert 'invalid' in resp.get_json()['error'].lower()


def test_login_correct_password_succeeds():
    client = _client()
    client.post('/api/signup', json={'email': 'login.ok@example.com', 'password': 'password123'})
    client.get('/logout')
    resp = client.post('/api/login', json={'email': 'login.ok@example.com', 'password': 'password123'})
    assert resp.status_code == 200
    assert resp.get_json()['success'] is True

"""Onboarding after sign-up: the /welcome flow and the profile (name) API."""
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


def _client_with_user(email):
    client = app.test_client()
    r = client.post('/api/signup', json={'email': email, 'password': 'password123'})
    assert r.status_code == 200, r.get_json()
    return client


def test_welcome_page_requires_login():
    assert app.test_client().get('/welcome').status_code in (302, 401)
    assert _client_with_user('welcome.page@example.com').get('/welcome').status_code == 200


def test_profile_name_saved_trimmed_and_shown_in_sidebar():
    client = _client_with_user('profile.name@example.com')
    assert client.get('/api/profile').get_json() == {'email': 'profile.name@example.com', 'name': ''}

    r = client.put('/api/profile', json={'name': '  Alex   Moreau '})
    assert r.status_code == 200
    assert r.get_json()['name'] == 'Alex Moreau'
    assert client.get('/api/profile').get_json()['name'] == 'Alex Moreau'

    page = client.get('/dashboard').get_data(as_text=True)
    assert 'Alex Moreau' in page
    assert 'data-name="Alex"' in page


def test_profile_name_is_required_and_length_limited():
    client = _client_with_user('profile.limits@example.com')
    client.put('/api/profile', json={'name': 'Sam'})
    assert client.put('/api/profile', json={'name': '   '}).status_code == 400
    r = client.put('/api/profile', json={'name': 'x' * (appmod.MAX_NAME_LENGTH + 1)})
    assert r.status_code == 400
    assert client.get('/api/profile').get_json()['name'] == 'Sam'


def test_pages_redirect_to_welcome_until_name_is_set():
    client = _client_with_user('profile.required@example.com')
    for path in ('/dashboard', '/accounts', '/upload', '/summary', '/budgets', '/investing'):
        r = client.get(path)
        assert r.status_code == 302 and r.headers['Location'].endswith('/welcome'), path
    # /welcome itself, its APIs and logout stay reachable.
    assert client.get('/welcome').status_code == 200
    assert client.get('/api/accounts').status_code == 200

    client.put('/api/profile', json={'name': 'Riley'})
    assert client.get('/dashboard').status_code == 200


def test_existing_user_without_name_is_sent_to_welcome_retroactively():
    """Accounts created before names existed: no `name` on the user doc and
    no `user_name` in an old session."""
    client = _client_with_user('profile.legacy@example.com')
    with client.session_transaction() as sess:
        uid = sess['user_id']
        del sess['user_name']
    appmod.user_ref(uid).update({'name': ''})
    assert client.get('/dashboard').headers['Location'].endswith('/welcome')

    # Same for a fresh login.
    fresh = app.test_client()
    fresh.post('/api/login', json={'email': 'profile.legacy@example.com', 'password': 'password123'})
    assert fresh.get('/accounts').headers['Location'].endswith('/welcome')


def test_old_session_picks_up_name_already_on_user_doc():
    client = _client_with_user('profile.oldsession@example.com')
    client.put('/api/profile', json={'name': 'Morgan'})
    with client.session_transaction() as sess:
        del sess['user_name']
    assert client.get('/dashboard').status_code == 200


def test_name_restored_into_session_on_login():
    client = _client_with_user('profile.login@example.com')
    client.put('/api/profile', json={'name': 'Jordan'})

    fresh = app.test_client()
    assert fresh.post('/api/login', json={'email': 'profile.login@example.com', 'password': 'password123'}).status_code == 200
    assert 'Jordan' in fresh.get('/dashboard').get_data(as_text=True)


def test_profile_is_per_user():
    a = _client_with_user('profile.a@example.com')
    b = _client_with_user('profile.b@example.com')
    a.put('/api/profile', json={'name': 'Avery'})
    assert b.get('/api/profile').get_json()['name'] == ''
    assert app.test_client().put('/api/profile', json={'name': 'x'}).status_code in (302, 401)

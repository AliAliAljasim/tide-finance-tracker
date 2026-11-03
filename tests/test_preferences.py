"""User menu: theme / hide-amounts preferences and changing the password."""
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


def _client_with_user(email, password='password123'):
    client = app.test_client()
    assert client.post('/api/signup', json={'email': email, 'password': password}).status_code == 200
    client.put('/api/profile', json={'name': 'Pat'})
    return client


def _html_tag(client, path='/dashboard'):
    page = client.get(path).get_data(as_text=True)
    return page[page.index('<html'):page.index('>', page.index('<html')) + 1]


def test_defaults_render_system_theme():
    client = _client_with_user('prefs.default@example.com')
    assert client.get('/api/preferences').get_json() == {'theme': 'system', 'hide_amounts': False}
    assert _html_tag(client) == '<html lang="en">'


def test_theme_and_hide_amounts_saved_and_rendered_on_every_shell():
    client = _client_with_user('prefs.dark@example.com')
    r = client.put('/api/preferences', json={'theme': 'dark', 'hide_amounts': True})
    assert r.get_json() == {'theme': 'dark', 'hide_amounts': True}
    assert _html_tag(client) == '<html lang="en" data-theme="dark" class="hide-amounts">'
    assert 'data-theme="dark"' in _html_tag(client, '/welcome')

    # Partial update keeps the other setting.
    client.put('/api/preferences', json={'hide_amounts': False})
    assert client.get('/api/preferences').get_json() == {'theme': 'dark', 'hide_amounts': False}


def test_preferences_follow_the_account_to_a_new_login():
    client = _client_with_user('prefs.login@example.com')
    client.put('/api/preferences', json={'theme': 'light'})
    fresh = app.test_client()
    fresh.post('/api/login', json={'email': 'prefs.login@example.com', 'password': 'password123'})
    assert 'data-theme="light"' in _html_tag(fresh)


def test_old_session_without_cached_prefs_loads_them():
    client = _client_with_user('prefs.oldsession@example.com')
    client.put('/api/preferences', json={'theme': 'dark'})
    with client.session_transaction() as sess:
        del sess['prefs']
    assert 'data-theme="dark"' in _html_tag(client)


def test_invalid_preferences_rejected():
    client = _client_with_user('prefs.invalid@example.com')
    assert client.put('/api/preferences', json={'theme': 'neon'}).status_code == 400
    assert client.put('/api/preferences', json={'hide_amounts': 'yes'}).status_code == 400
    assert app.test_client().put('/api/preferences', json={'theme': 'dark'}).status_code in (302, 401)


def test_logged_out_pages_use_system_theme():
    assert _html_tag(app.test_client(), '/login') == '<html lang="en">'


def test_change_password():
    client = _client_with_user('prefs.password@example.com')
    url = '/api/change-password'
    assert client.post(url, json={'current_password': 'wrong-pass', 'new_password': 'newpassword1'}).status_code == 400
    assert client.post(url, json={'current_password': 'password123', 'new_password': 'short'}).status_code == 400
    assert client.post(url, json={'current_password': 'password123', 'new_password': 'password123'}).status_code == 400
    assert client.post(url, json={'current_password': 'password123', 'new_password': 'newpassword1'}).status_code == 200

    fresh = app.test_client()
    login = {'email': 'prefs.password@example.com'}
    assert fresh.post('/api/login', json={**login, 'password': 'password123'}).status_code == 401
    assert fresh.post('/api/login', json={**login, 'password': 'newpassword1'}).status_code == 200


def test_user_menu_and_sidebar_toggle_on_signed_in_pages():
    page = _client_with_user('prefs.menu@example.com').get('/dashboard').get_data(as_text=True)
    for marker in ('id="userMenuBtn"', 'id="userMenu"', 'data-theme-choice="dark"', 'id="sideToggle"',
                   'id="hideAmountsToggle"', 'id="passwordDialog"'):
        assert marker in page, marker

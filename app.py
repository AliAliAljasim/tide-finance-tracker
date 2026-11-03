from flask import Flask, render_template, jsonify, request, session, redirect, url_for
from datetime import datetime, timedelta, timezone
from werkzeug.security import check_password_hash  # kept only for any legacy pbkdf2 hashes
from werkzeug.utils import secure_filename
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
import bcrypt
import os
import re
import uuid
from functools import wraps
from firestore_db import fs
from parsing import extract_text, mask_account_numbers, parse_statement_text, validate_transactions, ParsingError
from categorization import DEFAULT_CATEGORIES, categorize_transactions, detect_duplicates, normalize_merchant
import assistant
import llm
from registered import (ACCOUNT_TYPES as INVESTING_TYPES, FHSA_LIFETIME_LIMIT, RRSP_OVER_CONTRIBUTION_BUFFER,
                        compute_room, over_contribution)

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dev-finance-app-secret-key-change-in-production')
app.config['SESSION_PERMANENT'] = True
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(minutes=30)  # US-02: expire after 30 min idle
app.config['SESSION_REFRESH_EACH_REQUEST'] = True  # sliding window, not a fixed 30-minute cutoff
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['SESSION_COOKIE_SECURE'] = os.environ.get('FORCE_HTTPS', '') == '1'
app.config['MAX_CONTENT_LENGTH'] = 10 * 1024 * 1024  # US-04: 10 MB upload cap

UPLOAD_DIR = os.path.join(app.root_path, 'instance', 'uploads')
ALLOWED_EXTENSIONS = {'.pdf', '.jpg', '.jpeg', '.png'}
RESET_TOKEN_MAX_AGE = 60 * 60  # 1 hour, per US-03
ACCOUNT_TYPES = {'chequing', 'savings', 'credit_card'}
MAX_SUMMARY_MONTHS = 36  # guard against a huge/garbage from->to range
BUDGET_WARN_PCT = 80  # US-17: alert at 80% and again at 100%

reset_serializer = URLSafeTimedSerializer(app.config['SECRET_KEY'], salt='password-reset')

# ===== Optional HTTPS enforcement (NFR: "All pages served over HTTPS") =====
# Local dev has no TLS cert, so this only redirects when explicitly turned on
# (e.g. behind a reverse proxy that sets X-Forwarded-Proto). In production this
# would run behind a proxy/load balancer that terminates TLS and sets that header.

@app.before_request
def _enforce_https():
    if os.environ.get('FORCE_HTTPS') == '1' and request.headers.get('X-Forwarded-Proto', 'http') != 'https':
        return redirect(request.url.replace('http://', 'https://', 1), code=301)

# ===== Every signed-in user must have a name =====
# Retroactive: accounts created before names existed (or sessions from before
# then) are sent to the name step of /welcome before any other page loads.
# The JSON API stays reachable because /welcome itself is built on it.

NAME_EXEMPT_PREFIXES = ('/welcome', '/logout', '/static/', '/api/', '/forgot-password', '/reset-password/')

@app.before_request
def _require_name():
    if 'user_id' not in session or request.path.startswith(NAME_EXEMPT_PREFIXES):
        return None
    if 'user_name' not in session:
        session['user_name'] = (user_ref(get_user_id()).get().to_dict() or {}).get('name', '')
    if not session['user_name']:
        return redirect(url_for('welcome_page'))
    return None

# ===== Firestore-style helpers (see firestore_db.py) =====

def user_ref(uid):
    return fs.collection('users').document(uid)

def sub(uid, collection):
    return user_ref(uid).collection(collection)

def stream_docs(query):
    result = []
    for doc in query.stream():
        d = doc.to_dict() or {}
        d['_id'] = doc.id
        result.append(d)
    return result

def find_user_by_email(email):
    users = list(fs.collection('users').where('email', '==', email).limit(1).stream())
    return users[0] if users else None

def now_iso():
    return datetime.now(timezone.utc).isoformat()

# ===== Categories (global, not per-user — Sprint2.md's `categories` table) =====
# Seeded once; shared across every user, same as a real app's lookup table would be.

def get_categories():
    cats = stream_docs(fs.collection('categories'))
    if not cats:
        for c in DEFAULT_CATEGORIES:
            fs.collection('categories').add({'name': c['name'], 'kind': c['kind'], 'is_default': True, 'created_at': now_iso()})
        cats = stream_docs(fs.collection('categories'))
    return cats

def categories_by_name():
    return {c['name']: c for c in get_categories()}

def categories_by_id():
    return {c['_id']: c for c in get_categories()}

# ===== Merchant rules (US-12) =====

def get_merchant_rules(uid):
    """{merchant_key: category_id} for this user. Doc id *is* the merchant_key."""
    return {r['_id']: r.get('category_id') for r in stream_docs(sub(uid, 'merchant_rules'))}

def upsert_merchant_rule(uid, merchant_key, category_id):
    if not merchant_key:
        return
    sub(uid, 'merchant_rules').document(merchant_key).set({
        'merchant_key': merchant_key, 'category_id': category_id, 'updated_at': now_iso(),
    })

# ===== Account balances (US-10) =====

def recompute_account_balance(uid, account_id):
    acc_ref = sub(uid, 'accounts').document(account_id)
    acc = acc_ref.get().to_dict()
    if not acc:
        return None
    txs = [t for t in stream_docs(sub(uid, 'transactions'))
           if t.get('account_id') == account_id and t.get('confirmed')]
    credits = sum(float(t.get('amount') or 0) for t in txs if t.get('type') == 'credit')
    debits = sum(float(t.get('amount') or 0) for t in txs if t.get('type') == 'debit')
    opening = float(acc.get('opening_balance') or 0)
    if acc.get('type') == 'credit_card':
        # Balance *owed*: charges (debits) increase it, payments (credits) reduce it.
        balance = opening + debits - credits
    else:
        balance = opening + credits - debits
    balance = round(balance, 2)
    acc_ref.update({'current_balance': balance})
    return balance

# ===== Auth helpers =====

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

def get_user_id():
    uid = session.get('user_id')
    return str(uid) if uid is not None else None

EMAIL_RE = re.compile(r'^[^@\s]+@[^@\s]+\.[^@\s]+$')

def valid_email(email):
    return bool(email) and bool(EMAIL_RE.match(email))

def valid_password(password):
    if not password or len(password) < 8:
        return False, 'Password must be at least 8 characters.'
    return True, ''

def hash_password(password):
    return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

def check_password(password, stored_hash):
    if not stored_hash:
        return False
    try:
        return bcrypt.checkpw(password.encode('utf-8'), stored_hash.encode('utf-8'))
    except ValueError:
        # Fall back for any pre-existing werkzeug-hashed password.
        return check_password_hash(stored_hash, password)

def allowed_upload(filename, content_length):
    if not filename or '.' not in filename:
        return False, 'Choose a PDF, JPG or PNG file.'
    ext = os.path.splitext(filename)[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        return False, 'Unsupported file type. Please upload a PDF, JPG or PNG.'
    if content_length and content_length > app.config['MAX_CONTENT_LENGTH']:
        return False, 'File is too large. The limit is 10 MB.'
    return True, ''

def valid_account_fields(data, partial=False):
    """Returns (fields, error). `partial`=True allows a subset (PUT)."""
    fields = {}
    if 'name' in data or not partial:
        name = (data.get('name') or '').strip()
        if not name:
            return None, 'Account name is required.'
        fields['name'] = name
    if 'type' in data or not partial:
        acc_type = (data.get('type') or '').strip().lower()
        if acc_type not in ACCOUNT_TYPES:
            return None, 'Account type must be chequing, savings or credit_card.'
        fields['type'] = acc_type
    if 'institution' in data:
        fields['institution'] = (data.get('institution') or '').strip()
    elif not partial:
        fields['institution'] = ''
    if 'opening_balance' in data or not partial:
        try:
            fields['opening_balance'] = round(float(data.get('opening_balance') or 0), 2)
        except (TypeError, ValueError):
            return None, 'Opening balance must be a number.'
    return fields, None

@app.errorhandler(413)
def too_large(e):
    if request.path.startswith('/api/'):
        return jsonify({'error': 'File is too large. The limit is 10 MB.'}), 413
    return 'File is too large. The limit is 10 MB.', 413

# ===== Page routes =====

@app.route('/')
def index():
    return redirect(url_for('dashboard_page') if 'user_id' in session else url_for('login'))

@app.route('/signup')
def signup():
    if 'user_id' in session:
        return redirect(url_for('dashboard_page'))
    return render_template('signup.html')

@app.route('/login')
def login():
    if 'user_id' in session:
        return redirect(url_for('dashboard_page'))
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

@app.route('/forgot-password')
def forgot_password_page():
    return render_template('forgot_password.html')

@app.route('/reset-password/<token>')
def reset_password_page(token):
    try:
        reset_serializer.loads(token, max_age=RESET_TOKEN_MAX_AGE)
        token_valid = True
    except (BadSignature, SignatureExpired):
        token_valid = False
    return render_template('reset_password.html', token=token, token_valid=token_valid)

@app.route('/welcome')
@login_required
def welcome_page():
    return render_template('welcome.html')

@app.route('/dashboard')
@login_required
def dashboard_page():
    return render_template('dashboard.html')

@app.route('/accounts')
@login_required
def accounts_page():
    return render_template('accounts.html')

@app.route('/accounts/<account_id>')
@login_required
def account_detail_page(account_id):
    uid = get_user_id()
    if not sub(uid, 'accounts').document(account_id).get().exists:
        return redirect(url_for('accounts_page'))
    return render_template('account_detail.html', account_id=account_id)

@app.route('/upload')
@login_required
def upload_page():
    return render_template('upload.html')

@app.route('/review/<statement_id>')
@login_required
def review_page(statement_id):
    uid = get_user_id()
    doc = sub(uid, 'statements').document(statement_id).get()
    if not doc.exists:
        return redirect(url_for('upload_page'))
    return render_template('review.html', statement_id=statement_id)

@app.route('/summary')
@login_required
def summary_page():
    return render_template('summary.html')

@app.route('/budgets')
@login_required
def budgets_page():
    return render_template('budgets.html')

@app.route('/investing')
@login_required
def investing_page():
    return render_template('registered.html')

@app.route('/investing/<account_id>')
@login_required
def investing_detail_page(account_id):
    uid = get_user_id()
    if not sub(uid, 'registered_accounts').document(account_id).get().exists:
        return redirect(url_for('investing_page'))
    return render_template('registered_detail.html', account_id=account_id)

# Old TFSA & FHSA links and bookmarks.
@app.route('/registered')
@app.route('/registered/<account_id>')
def registered_redirect(account_id=None):
    return redirect(url_for('investing_detail_page', account_id=account_id) if account_id
                    else url_for('investing_page'), code=301)

# ===== Auth API =====

@app.route('/api/signup', methods=['POST'])
def api_signup():
    data = request.get_json(silent=True) or {}
    email = (data.get('email') or '').lower().strip()
    password = data.get('password', '')

    if not valid_email(email):
        return jsonify({'error': 'Please enter a valid email address.'}), 400
    ok, msg = valid_password(password)
    if not ok:
        return jsonify({'error': msg}), 400
    if find_user_by_email(email):
        return jsonify({'error': 'An account with that email already exists.'}), 400

    _, user_doc_ref = fs.collection('users').add({
        'email': email,
        'password_hash': hash_password(password),
        'created_at': now_iso(),
    })
    uid = user_doc_ref.id
    session.permanent = True
    session['user_id'] = uid
    session['user_email'] = email
    session['user_name'] = ''
    session['prefs'] = clean_prefs(None)
    return jsonify({'success': True})

@app.route('/api/login', methods=['POST'])
def api_login():
    data = request.get_json(silent=True) or {}
    email = (data.get('email') or '').lower().strip()
    password = data.get('password', '')
    if not email or not password:
        return jsonify({'error': 'Enter your email and password.'}), 400

    user_doc = find_user_by_email(email)
    if not user_doc or not check_password(password, (user_doc.to_dict() or {}).get('password_hash', '')):
        return jsonify({'error': 'Invalid email or password.'}), 401

    user = user_doc.to_dict()
    session.permanent = True
    session['user_id'] = user_doc.id
    session['user_email'] = user.get('email')
    session['user_name'] = user.get('name', '')
    session['prefs'] = clean_prefs(user.get('preferences'))
    return jsonify({'success': True})

# ===== Profile (onboarding) =====

MAX_NAME_LENGTH = 60

# ===== Preferences (user menu) =====
# Stored on the user doc so they follow the account across devices, and
# cached in the session so every page can render them server-side (the theme
# is set on <html> before first paint, so there's no flash of the wrong one).

THEMES = ('system', 'light', 'dark')
DEFAULT_PREFS = {'theme': 'system', 'hide_amounts': False}

def clean_prefs(prefs):
    prefs = prefs if isinstance(prefs, dict) else {}
    return {'theme': prefs.get('theme') if prefs.get('theme') in THEMES else 'system',
            'hide_amounts': prefs.get('hide_amounts') is True}

@app.context_processor
def inject_prefs():
    if 'user_id' not in session:
        return {'prefs': dict(DEFAULT_PREFS)}
    if 'prefs' not in session:  # sessions from before preferences existed
        session['prefs'] = clean_prefs((user_ref(get_user_id()).get().to_dict() or {}).get('preferences'))
    return {'prefs': session['prefs']}

@app.route('/api/preferences', methods=['GET'])
@login_required
def api_get_preferences():
    return jsonify(clean_prefs((user_ref(get_user_id()).get().to_dict() or {}).get('preferences')))

@app.route('/api/preferences', methods=['PUT'])
@login_required
def api_update_preferences():
    data = request.get_json(silent=True) or {}
    if 'theme' in data and data['theme'] not in THEMES:
        return jsonify({'error': 'Theme must be system, light or dark.'}), 400
    if 'hide_amounts' in data and not isinstance(data['hide_amounts'], bool):
        return jsonify({'error': 'hide_amounts must be true or false.'}), 400
    ref = user_ref(get_user_id())
    current = clean_prefs((ref.get().to_dict() or {}).get('preferences'))
    prefs = clean_prefs({**current, **{k: data[k] for k in DEFAULT_PREFS if k in data}})
    ref.update({'preferences': prefs})
    session['prefs'] = prefs
    return jsonify(prefs)

@app.route('/api/change-password', methods=['POST'])
@login_required
def api_change_password():
    data = request.get_json(silent=True) or {}
    ref = user_ref(get_user_id())
    user = ref.get().to_dict() or {}
    if not check_password(data.get('current_password') or '', user.get('password_hash', '')):
        return jsonify({'error': 'Your current password is incorrect.'}), 400
    new = data.get('new_password') or ''
    ok, msg = valid_password(new)
    if not ok:
        return jsonify({'error': msg}), 400
    if new == data.get('current_password'):
        return jsonify({'error': 'Choose a password different from your current one.'}), 400
    ref.update({'password_hash': hash_password(new)})
    return jsonify({'success': True})

@app.route('/api/profile', methods=['GET'])
@login_required
def api_get_profile():
    user = user_ref(get_user_id()).get().to_dict() or {}
    return jsonify({'email': user.get('email', ''), 'name': user.get('name', '')})

@app.route('/api/profile', methods=['PUT'])
@login_required
def api_update_profile():
    data = request.get_json(silent=True) or {}
    name = ' '.join((data.get('name') or '').split())
    if not name:
        return jsonify({'error': 'Please enter your name.'}), 400
    if len(name) > MAX_NAME_LENGTH:
        return jsonify({'error': f'Name must be {MAX_NAME_LENGTH} characters or fewer.'}), 400
    user_ref(get_user_id()).update({'name': name})
    session['user_name'] = name
    return jsonify({'success': True, 'name': name})

@app.route('/api/forgot-password', methods=['POST'])
def api_forgot_password():
    data = request.get_json(silent=True) or {}
    email = (data.get('email') or '').lower().strip()
    user_doc = find_user_by_email(email) if email else None

    # Always respond the same way whether or not the email is registered,
    # so this endpoint can't be used to find out which emails have accounts.
    if user_doc:
        token = reset_serializer.dumps(user_doc.id)
        reset_url = url_for('reset_password_page', token=token, _external=True)
        # No SMTP service is wired up for this sprint, so the "email" is a
        # console log. In production this would hand reset_url to a real
        # mailer (e.g. SES/SendGrid) instead of printing it.
        print(f'[DEV] Password reset link for {email}: {reset_url}')
        response = {'success': True, 'message': 'If that email has an account, a reset link has been sent.'}
        if app.debug:
            response['dev_reset_url'] = reset_url  # convenience for local testing only
        return jsonify(response)

    return jsonify({'success': True, 'message': 'If that email has an account, a reset link has been sent.'})

@app.route('/api/reset-password', methods=['POST'])
def api_reset_password():
    data = request.get_json(silent=True) or {}
    token = data.get('token', '')
    password = data.get('password', '')

    try:
        uid = reset_serializer.loads(token, max_age=RESET_TOKEN_MAX_AGE)
    except SignatureExpired:
        return jsonify({'error': 'This reset link has expired. Please request a new one.'}), 400
    except BadSignature:
        return jsonify({'error': 'This reset link is invalid.'}), 400

    ok, msg = valid_password(password)
    if not ok:
        return jsonify({'error': msg}), 400

    doc_ref = user_ref(uid)
    if not doc_ref.get().exists:
        return jsonify({'error': 'This reset link is invalid.'}), 400

    doc_ref.update({'password_hash': hash_password(password)})
    return jsonify({'success': True})

# ===== Categories =====

@app.route('/api/categories', methods=['GET'])
@login_required
def api_list_categories():
    return jsonify({'categories': get_categories()})

# ===== Accounts (US-09) =====

@app.route('/api/accounts', methods=['GET'])
@login_required
def api_list_accounts():
    uid = get_user_id()
    accounts = stream_docs(sub(uid, 'accounts'))
    accounts.sort(key=lambda a: a.get('created_at', ''))
    return jsonify({'accounts': accounts})

@app.route('/api/accounts', methods=['POST'])
@login_required
def api_create_account():
    uid = get_user_id()
    data = request.get_json(silent=True) or {}
    fields, error = valid_account_fields(data)
    if error:
        return jsonify({'error': error}), 400
    fields['current_balance'] = fields['opening_balance']
    fields['created_at'] = now_iso()
    _, ref = sub(uid, 'accounts').add(fields)
    return jsonify({'success': True, 'account': {**fields, '_id': ref.id}})

@app.route('/api/accounts/<account_id>', methods=['GET'])
@login_required
def api_get_account(account_id):
    uid = get_user_id()
    doc = sub(uid, 'accounts').document(account_id).get()
    if not doc.exists:
        return jsonify({'error': 'Account not found.'}), 404
    account = doc.to_dict()
    account['_id'] = account_id

    cats_by_id = categories_by_id()
    txs = [t for t in stream_docs(sub(uid, 'transactions'))
           if t.get('account_id') == account_id and t.get('confirmed')]
    for t in txs:
        t['category_name'] = cats_by_id.get(t.get('category_id'), {}).get('name', 'Other')
    txs.sort(key=lambda t: t.get('date', ''), reverse=True)

    return jsonify({'account': account, 'transactions': txs})

@app.route('/api/accounts/<account_id>', methods=['PUT'])
@login_required
def api_update_account(account_id):
    uid = get_user_id()
    ref = sub(uid, 'accounts').document(account_id)
    if not ref.get().exists:
        return jsonify({'error': 'Account not found.'}), 404
    data = request.get_json(silent=True) or {}
    fields, error = valid_account_fields(data, partial=True)
    if error:
        return jsonify({'error': error}), 400
    if fields:
        ref.update(fields)
    if 'opening_balance' in fields or 'type' in fields:
        recompute_account_balance(uid, account_id)
    return jsonify({'success': True, 'account': ref.get().to_dict()})

@app.route('/api/accounts/<account_id>', methods=['DELETE'])
@login_required
def api_delete_account(account_id):
    uid = get_user_id()
    ref = sub(uid, 'accounts').document(account_id)
    if not ref.get().exists:
        return jsonify({'error': 'Account not found.'}), 404

    force = request.args.get('force') == 'true' or (request.get_json(silent=True) or {}).get('force') is True
    tx_sub = sub(uid, 'transactions')
    account_txs = [t for t in stream_docs(tx_sub) if t.get('account_id') == account_id]

    if account_txs and not force:
        return jsonify({
            'error': f'This account has {len(account_txs)} transaction(s). Delete it anyway?',
            'confirm_required': True,
            'transaction_count': len(account_txs),
        }), 409

    stmt_sub = sub(uid, 'statements')
    for s in stream_docs(stmt_sub):
        if s.get('account_id') == account_id:
            file_path = s.get('file_path')
            if file_path and os.path.exists(file_path):
                os.remove(file_path)
            stmt_sub.document(s['_id']).delete()
    for t in account_txs:
        tx_sub.document(t['_id']).delete()
    ref.delete()
    return jsonify({'success': True})

# ===== Statement upload & AI parsing pipeline (US-04, US-05, US-06, US-10) =====

@app.route('/api/statements', methods=['GET'])
@login_required
def api_list_statements():
    uid = get_user_id()
    statements = stream_docs(sub(uid, 'statements'))
    accounts_by_id = {a['_id']: a for a in stream_docs(sub(uid, 'accounts'))}
    for s in statements:
        s['account_name'] = accounts_by_id.get(s.get('account_id'), {}).get('name', 'Unknown account')
    statements.sort(key=lambda s: s.get('created_at', ''), reverse=True)
    return jsonify({'statements': statements})

@app.route('/api/upload', methods=['POST'])
@login_required
def api_upload():
    uid = get_user_id()
    account_id = request.form.get('account_id', '')
    period_start = request.form.get('period_start') or None
    period_end = request.form.get('period_end') or None
    file = request.files.get('file')

    if not account_id or not sub(uid, 'accounts').document(account_id).get().exists:
        return jsonify({'error': 'Choose an account for this statement.'}), 400
    if file is None or file.filename == '':
        return jsonify({'error': 'Choose a file to upload.'}), 400

    ok, msg = allowed_upload(file.filename, request.content_length)
    if not ok:
        return jsonify({'error': msg}), 400

    statement_id = uuid.uuid4().hex
    ext = os.path.splitext(secure_filename(file.filename))[1].lower()
    user_upload_dir = os.path.join(UPLOAD_DIR, uid)
    os.makedirs(user_upload_dir, exist_ok=True)
    file_path = os.path.join(user_upload_dir, f'{statement_id}{ext}')
    file.save(file_path)

    # Re-check size on disk in case Content-Length was absent/wrong.
    if os.path.getsize(file_path) > app.config['MAX_CONTENT_LENGTH']:
        os.remove(file_path)
        return jsonify({'error': 'File is too large. The limit is 10 MB.'}), 400

    statements_ref = sub(uid, 'statements')
    statements_ref.document(statement_id).set({
        'account_id': account_id,
        'original_filename': file.filename,
        'file_path': file_path,
        'period_start': period_start,
        'period_end': period_end,
        'status': 'processing',
        'created_at': now_iso(),
    })

    try:
        raw_text, needs_ocr_failed = extract_text(file_path, ext)
        if not raw_text or not raw_text.strip():
            reason = ('Could not read this image (OCR is not available in this environment).'
                      if needs_ocr_failed else
                      'Could not read any text from this statement.')
            raise ParsingError(reason)

        masked_text = mask_account_numbers(raw_text)
        parsed = parse_statement_text(masked_text)  # 1 record per transaction, per the fixed schema
        period_start = period_start or parsed.get('period_start')
        period_end = period_end or parsed.get('period_end')
        transactions, balance_ok = validate_transactions(
            parsed.get('transactions', []),
            parsed.get('opening_balance'),
            parsed.get('closing_balance'),
            period_start, period_end,
        )

        # US-11: categorize (merchant rule -> keyword -> batched LLM -> default).
        categorize_transactions(transactions, categories_by_name(), get_merchant_rules(uid))

        # US-08: flag rows that match an already-confirmed transaction in this
        # account (same date, amount, merchant_key) — e.g. a re-uploaded,
        # overlapping statement.
        existing_confirmed = [t for t in stream_docs(sub(uid, 'transactions'))
                               if t.get('account_id') == account_id and t.get('confirmed')]
        detect_duplicates(transactions, existing_confirmed)
    except ParsingError as e:
        os.remove(file_path)
        statements_ref.document(statement_id).update({'status': 'failed', 'error': str(e)})
        return jsonify({'error': str(e), 'retry': True}), 422
    except Exception as e:
        if os.path.exists(file_path):
            os.remove(file_path)
        statements_ref.document(statement_id).update({'status': 'failed', 'error': 'Unexpected error while parsing.'})
        return jsonify({'error': 'Something went wrong while parsing this statement. Please try again.', 'retry': True}), 500

    tx_sub = sub(uid, 'transactions')
    for tx in transactions:
        tx_sub.add({**tx, 'account_id': account_id, 'statement_id': statement_id, 'confirmed': False})

    statements_ref.document(statement_id).update({
        'status': 'parsed',
        'period_start': period_start,
        'period_end': period_end,
        'opening_balance': parsed.get('opening_balance'),
        'closing_balance': parsed.get('closing_balance'),
        'balance_ok': balance_ok,
    })

    return jsonify({'success': True, 'statement_id': statement_id})

@app.route('/api/statements/<statement_id>', methods=['GET'])
@login_required
def api_get_statement(statement_id):
    uid = get_user_id()
    doc = sub(uid, 'statements').document(statement_id).get()
    if not doc.exists:
        return jsonify({'error': 'Statement not found.'}), 404
    statement = doc.to_dict()
    statement['_id'] = statement_id
    cats_by_id = categories_by_id()
    transactions = [t for t in stream_docs(sub(uid, 'transactions')) if t.get('statement_id') == statement_id]
    for t in transactions:
        t['category_name'] = cats_by_id.get(t.get('category_id'), {}).get('name', 'Other')
    transactions.sort(key=lambda t: t.get('date', ''))
    return jsonify({'statement': statement, 'transactions': transactions, 'categories': get_categories()})

@app.route('/api/statements/<statement_id>/transactions', methods=['POST'])
@login_required
def api_add_transaction(statement_id):
    uid = get_user_id()
    stmt_doc = sub(uid, 'statements').document(statement_id).get()
    if not stmt_doc.exists:
        return jsonify({'error': 'Statement not found.'}), 404
    data = request.get_json(silent=True) or {}
    tx = {
        'date': data.get('date', ''),
        'description': data.get('description', ''),
        'amount': float(data.get('amount') or 0),
        'type': data.get('type') if data.get('type') in ('debit', 'credit') else 'debit',
        'balance': data.get('balance'),
        'flagged': False,
        'flag_reason': '',
    }
    categorize_transactions([tx], categories_by_name(), get_merchant_rules(uid))
    tx['is_duplicate'] = False
    tx['account_id'] = stmt_doc.to_dict().get('account_id')
    tx['statement_id'] = statement_id
    tx['confirmed'] = False
    _, ref = sub(uid, 'transactions').add(tx)
    tx['_id'] = ref.id
    tx['category_name'] = categories_by_id().get(tx['category_id'], {}).get('name', 'Other')
    return jsonify({'success': True, 'transaction': tx})

@app.route('/api/statements/<statement_id>/transactions/<tx_id>', methods=['PUT'])
@login_required
def api_update_transaction(statement_id, tx_id):
    uid = get_user_id()
    ref = sub(uid, 'transactions').document(tx_id)
    tx_doc = ref.get()
    if not tx_doc.exists:
        return jsonify({'error': 'Transaction not found.'}), 404
    tx = tx_doc.to_dict()
    data = request.get_json(silent=True) or {}
    updates = {}
    for field in ('date', 'description', 'type'):
        if field in data:
            updates[field] = data[field]
    if 'amount' in data:
        updates['amount'] = float(data['amount'] or 0)
    if 'balance' in data:
        updates['balance'] = data['balance']
    if 'is_duplicate' in data:
        updates['is_duplicate'] = bool(data['is_duplicate'])

    # US-12: changing the category remembers it for this merchant going forward,
    # and optionally applies it to that merchant's other transactions right now.
    if 'category_id' in data and data['category_id'] and data['category_id'] != tx.get('category_id'):
        updates['category_id'] = data['category_id']
        merchant_key = tx.get('merchant_key') or normalize_merchant(tx.get('description'))
        upsert_merchant_rule(uid, merchant_key, data['category_id'])
        if data.get('apply_to_all') and merchant_key:
            tx_sub = sub(uid, 'transactions')
            for other in stream_docs(tx_sub):
                if other['_id'] != tx_id and other.get('merchant_key') == merchant_key:
                    tx_sub.document(other['_id']).update({'category_id': data['category_id']})

    if updates:
        ref.update(updates)
    return jsonify({'success': True})

@app.route('/api/statements/<statement_id>/transactions/<tx_id>', methods=['DELETE'])
@login_required
def api_delete_transaction(statement_id, tx_id):
    uid = get_user_id()
    sub(uid, 'transactions').document(tx_id).delete()
    return jsonify({'success': True})

@app.route('/api/statements/<statement_id>/confirm', methods=['POST'])
@login_required
def api_confirm_statement(statement_id):
    uid = get_user_id()
    stmt_ref = sub(uid, 'statements').document(statement_id)
    stmt_doc = stmt_ref.get()
    if not stmt_doc.exists:
        return jsonify({'error': 'Statement not found.'}), 404
    statement = stmt_doc.to_dict()

    transactions = [t for t in stream_docs(sub(uid, 'transactions')) if t.get('statement_id') == statement_id]
    # Balance/date flagging runs over every row — it's about the statement's
    # own internal consistency and is unrelated to cross-statement duplicates.
    transactions, balance_ok = validate_transactions(
        transactions, statement.get('opening_balance'), statement.get('closing_balance'),
        statement.get('period_start'), statement.get('period_end'),
    )
    tx_sub = sub(uid, 'transactions')

    # US-08: "Skipped rows are not saved." A row still flagged is_duplicate
    # here means the user never resolved it (never clicked Keep), so it's
    # treated as skipped automatically — this is what actually guarantees an
    # overlapping re-upload can never double-count, rather than relying on
    # the user to act on every flag.
    skipped = 0
    for tx in transactions:
        if tx.get('is_duplicate'):
            tx_sub.document(tx['_id']).delete()
            skipped += 1
        else:
            tx_sub.document(tx['_id']).update({'flagged': tx['flagged'], 'flag_reason': tx['flag_reason'], 'confirmed': True})

    # US-07: "Nothing is saved until the user clicks Confirm" — the rows were
    # already written so they're editable; confirming locks them in and, per
    # the privacy requirement, deletes the uploaded file.
    file_path = statement.get('file_path')
    if file_path and os.path.exists(file_path):
        os.remove(file_path)
    stmt_ref.update({'status': 'confirmed', 'balance_ok': balance_ok, 'confirmed_at': now_iso()})

    # US-10: recalculate the linked account's balance now that these are confirmed.
    new_balance = recompute_account_balance(uid, statement.get('account_id'))
    return jsonify({'success': True, 'account_balance': new_balance, 'skipped_duplicates': skipped})

@app.route('/api/statements/<statement_id>', methods=['DELETE'])
@login_required
def api_discard_statement(statement_id):
    uid = get_user_id()
    stmt_ref = sub(uid, 'statements').document(statement_id)
    stmt_doc = stmt_ref.get()
    if stmt_doc.exists:
        file_path = stmt_doc.to_dict().get('file_path')
        if file_path and os.path.exists(file_path):
            os.remove(file_path)
        for t in stream_docs(sub(uid, 'transactions')):
            if t.get('statement_id') == statement_id:
                sub(uid, 'transactions').document(t['_id']).delete()
        stmt_ref.delete()
    return jsonify({'success': True})

# ===== Summaries (US-13, US-14) =====

def month_range(from_month, to_month):
    y1, m1 = (int(x) for x in from_month.split('-'))
    y2, m2 = (int(x) for x in to_month.split('-'))
    months = []
    y, m = y1, m1
    while (y, m) <= (y2, m2) and len(months) < MAX_SUMMARY_MONTHS:
        months.append(f'{y:04d}-{m:02d}')
        m += 1
        if m == 13:
            m = 1
            y += 1
    return months

def confirmed_transactions(uid, account_id):
    txs = [t for t in stream_docs(sub(uid, 'transactions')) if t.get('confirmed')]
    if account_id and account_id != 'all':
        txs = [t for t in txs if t.get('account_id') == account_id]
    return txs

@app.route('/api/transactions/recent', methods=['GET'])
@login_required
def api_recent_transactions():
    """Latest confirmed transactions across all accounts, for the dashboard."""
    uid = get_user_id()
    try:
        limit = min(max(int(request.args.get('limit', 8)), 1), 50)
    except ValueError:
        return jsonify({'error': 'Limit must be a number.'}), 400
    cats_by_id = categories_by_id()
    accounts_by_id = {a['_id']: a for a in stream_docs(sub(uid, 'accounts'))}
    rows = sorted(confirmed_transactions(uid, 'all'), key=lambda t: (t.get('date') or '', t.get('created_at') or ''), reverse=True)[:limit]
    for t in rows:
        cat = cats_by_id.get(t.get('category_id'), {})
        t['category_name'] = cat.get('name', 'Other')
        t['category_kind'] = cat.get('kind', 'expense')
        t['account_name'] = accounts_by_id.get(t.get('account_id'), {}).get('name', 'Unknown account')
    return jsonify({'transactions': rows})

@app.route('/api/summary/monthly', methods=['GET'])
@login_required
def api_summary_monthly():
    uid = get_user_id()
    current_month = datetime.now(timezone.utc).strftime('%Y-%m')
    from_month = request.args.get('from') or current_month
    to_month = request.args.get('to') or current_month
    account_id = request.args.get('account', 'all')
    if to_month < from_month:
        from_month, to_month = to_month, from_month

    months = month_range(from_month, to_month)
    transfers_id = categories_by_name().get('Transfers', {}).get('_id')
    totals = {m: {'income': 0.0, 'expenses': 0.0} for m in months}

    for t in confirmed_transactions(uid, account_id):
        m = (t.get('date') or '')[:7]
        if m not in totals or t.get('category_id') == transfers_id:
            continue
        amount = float(t.get('amount') or 0)
        if t.get('type') == 'credit':
            totals[m]['income'] += amount
        else:
            totals[m]['expenses'] += amount

    result = [{
        'month': m,
        'income': round(totals[m]['income'], 2),
        'expenses': round(totals[m]['expenses'], 2),
        'net': round(totals[m]['income'] - totals[m]['expenses'], 2),
    } for m in months]
    return jsonify({'months': result})

@app.route('/api/summary/categories', methods=['GET'])
@login_required
def api_summary_categories():
    uid = get_user_id()
    month = request.args.get('month') or datetime.now(timezone.utc).strftime('%Y-%m')
    account_id = request.args.get('account', 'all')
    cats_by_id = categories_by_id()
    transfers_id = categories_by_name().get('Transfers', {}).get('_id')

    totals = {}
    for t in confirmed_transactions(uid, account_id):
        if t.get('type') != 'debit':
            continue
        if (t.get('date') or '')[:7] != month:
            continue
        cat_id = t.get('category_id')
        if cat_id == transfers_id:
            continue
        totals[cat_id] = totals.get(cat_id, 0.0) + float(t.get('amount') or 0)

    rows = [{'category_id': cid, 'category': cats_by_id.get(cid, {}).get('name', 'Other'), 'total': round(total, 2)}
            for cid, total in totals.items()]
    rows.sort(key=lambda r: r['total'], reverse=True)
    return jsonify({'categories': rows, 'month': month})

@app.route('/api/summary/categories/transactions', methods=['GET'])
@login_required
def api_summary_category_transactions():
    uid = get_user_id()
    month = request.args.get('month') or datetime.now(timezone.utc).strftime('%Y-%m')
    account_id = request.args.get('account', 'all')
    category_id = request.args.get('category_id', '')

    rows = [t for t in confirmed_transactions(uid, account_id)
            if t.get('type') == 'debit' and (t.get('date') or '')[:7] == month and t.get('category_id') == category_id]
    rows.sort(key=lambda t: t.get('date', ''))
    return jsonify({'transactions': rows})

# ===== Budgets (US-15, US-16, US-17) =====
# One budget per expense category, doc id = category_id. The amount repeats
# every month; spending is that month's confirmed debits across all accounts.

def valid_month(value):
    return bool(re.fullmatch(r'\d{4}-(0[1-9]|1[0-2])', value or ''))

def budget_status(pct):
    if pct >= 100:
        return 'over'
    if pct >= BUDGET_WARN_PCT:
        return 'warning'
    return 'ok'

def budget_report(uid, month):
    cats_by_id = categories_by_id()
    spent = {}
    for t in confirmed_transactions(uid, 'all'):
        if t.get('type') == 'debit' and (t.get('date') or '')[:7] == month:
            spent[t.get('category_id')] = spent.get(t.get('category_id'), 0.0) + float(t.get('amount') or 0)

    rows, alerts = [], []
    for b in stream_docs(sub(uid, 'budgets')):
        cat = cats_by_id.get(b['_id'])
        if not cat:
            continue
        amount = float(b.get('amount') or 0)
        cat_spent = round(spent.get(b['_id'], 0.0), 2)
        raw_pct = cat_spent / amount * 100 if amount else 0.0
        status = budget_status(raw_pct)  # unrounded, so 79.99% isn't flagged as 80%
        pct = round(raw_pct, 1)
        rows.append({
            'category_id': b['_id'], 'category': cat['name'], 'amount': round(amount, 2),
            'spent': cat_spent, 'remaining': round(amount - cat_spent, 2), 'pct': pct, 'status': status,
        })
        if status == 'over':
            over_by = round(cat_spent - amount, 2)
            alerts.append({'category_id': b['_id'], 'category': cat['name'], 'level': 'over', 'pct': pct,
                           'message': f"{cat['name']} is over budget by ${over_by:,.2f}." if over_by > 0
                                      else f"{cat['name']} has used its whole budget."})
        elif status == 'warning':
            alerts.append({'category_id': b['_id'], 'category': cat['name'], 'level': 'warning', 'pct': pct,
                           'message': f"{cat['name']} is at {pct:.0f}% of its budget."})

    rows.sort(key=lambda r: r['category'])
    alerts.sort(key=lambda a: -a['pct'])
    total_amount = round(sum(r['amount'] for r in rows), 2)
    total_spent = round(sum(r['spent'] for r in rows), 2)
    return {
        'month': month, 'budgets': rows, 'alerts': alerts,
        'totals': {'amount': total_amount, 'spent': total_spent, 'remaining': round(total_amount - total_spent, 2)},
    }

@app.route('/api/budgets', methods=['GET'])
@login_required
def api_list_budgets():
    month = request.args.get('month') or datetime.now(timezone.utc).strftime('%Y-%m')
    if not valid_month(month):
        return jsonify({'error': 'Month must look like YYYY-MM.'}), 400
    return jsonify(budget_report(get_user_id(), month))

@app.route('/api/budgets/<category_id>', methods=['PUT'])
@login_required
def api_set_budget(category_id):
    uid = get_user_id()
    cat = categories_by_id().get(category_id)
    if not cat or cat.get('kind') != 'expense' or cat.get('name') == 'Transfers':
        return jsonify({'error': 'Choose a spending category for this budget.'}), 400
    data = request.get_json(silent=True) or {}
    try:
        amount = round(float(data.get('amount')), 2)
    except (TypeError, ValueError):
        return jsonify({'error': 'Budget amount must be a number.'}), 400
    if amount <= 0:
        return jsonify({'error': 'Budget amount must be more than $0.'}), 400
    sub(uid, 'budgets').document(category_id).set({'category_id': category_id, 'amount': amount, 'updated_at': now_iso()})
    return jsonify({'success': True})

@app.route('/api/budgets/<category_id>', methods=['DELETE'])
@login_required
def api_delete_budget(category_id):
    sub(get_user_id(), 'budgets').document(category_id).delete()
    return jsonify({'success': True})

# ===== Investing: TFSA, FHSA, RRSP, RESP, RDSP, LIRA, RRIF, non-registered (US-18..US-20) =====
# Kept apart from bank `accounts`: these have no statements or balance, just
# contribution room / limits and a log of contributions and withdrawals (see
# registered.py). Stored as `registered_accounts` for backwards compatibility,
# even though non-registered accounts live here too.

def current_year():
    return datetime.now(timezone.utc).year

def valid_registered_fields(data, existing=None):
    """Returns (fields, error). `existing` is the stored doc when editing."""
    merged = {**(existing or {}), **data}
    fields = {}
    name = (merged.get('name') or '').strip()
    if not name:
        return None, 'Account name is required.'
    fields['name'] = name
    acc_type = (merged.get('type') or '').strip().lower()
    if acc_type not in INVESTING_TYPES:
        return None, 'Choose an account type: ' + ', '.join(t['label'] for t in INVESTING_TYPES.values()) + '.'
    if existing and acc_type != existing.get('type'):
        return None, "An account's type can't be changed."
    meta = INVESTING_TYPES[acc_type]
    fields['type'] = acc_type
    fields['institution'] = (merged.get('institution') or '').strip()
    # Only the numbers that mean something for this type are kept; the rest are 0.
    uses_room = meta['kind'] == 'annual'
    uses_prior = acc_type == 'fhsa' or meta['kind'] == 'lifetime'
    try:
        fields['starting_room'] = round(float(merged.get('starting_room') or 0), 2) if uses_room else 0.0
        fields['start_year'] = int(merged.get('start_year') or current_year())
        fields['prior_contributions'] = round(float(merged.get('prior_contributions') or 0), 2) if uses_prior else 0.0
        fields['annual_room'] = round(float(merged.get('annual_room') or 0), 2) if acc_type == 'rrsp' else 0.0
    except (TypeError, ValueError):
        return None, 'Room, year and contribution amounts must be numbers.'
    if min(fields['starting_room'], fields['prior_contributions'], fields['annual_room']) < 0:
        return None, "Room and contribution amounts can't be negative."
    if not meta['first_year'] <= fields['start_year'] <= current_year():
        return None, f"Start year must be between {meta['first_year']} and {current_year()}."
    cap = FHSA_LIFETIME_LIMIT if acc_type == 'fhsa' else meta.get('lifetime_limit')
    if cap and fields['prior_contributions'] > cap:
        return None, f"{meta['label']} contributions are capped at ${cap:,} for life."
    return fields, None

def registered_transactions(uid, account_id):
    return [t for t in stream_docs(sub(uid, 'registered_transactions')) if t.get('account_id') == account_id]

def with_room(account, txs):
    years = compute_room(account, txs, current_year())
    meta = INVESTING_TYPES[account['type']]
    return {**account, 'label': meta['label'], 'type_name': meta['name'], 'kind': meta['kind'],
            'lifetime_limit': FHSA_LIFETIME_LIMIT if account['type'] == 'fhsa' else meta.get('lifetime_limit'),
            'current': years[-1], 'years': years}

def over_contribution_message(account, txs, over_by):
    meta = INVESTING_TYPES[account['type']]
    label = meta['label']
    cap = FHSA_LIFETIME_LIMIT if account['type'] == 'fhsa' else meta.get('lifetime_limit')
    if cap:
        # Lifetime total only grows, so the latest year shows how far past the cap it goes.
        latest = compute_room(account, txs, current_year())[-1]
        if -latest['lifetime_remaining'] >= over_by:
            penalty = ('Excess contributions are taxed 1% per month.' if account['type'] == 'fhsa'
                       else 'CRA charges a penalty tax on contributions over the limit.')
            return (f'This contribution would take you ${over_by:,.2f} over the ${cap:,} {label} lifetime limit. '
                    f'{penalty} Save it anyway?')
    if account['type'] == 'rrsp':
        return (f'This contribution would put you ${over_by:,.2f} past your RRSP deduction limit plus the '
                f'${RRSP_OVER_CONTRIBUTION_BUFFER:,} cushion. The excess is taxed 1% per month. Save it anyway?')
    return (f'This contribution would put you ${over_by:,.2f} over your {label} contribution room. '
            'Excess contributions are taxed 1% per month. Save it anyway?')

@app.route('/api/registered', methods=['GET'])
@login_required
def api_list_registered():
    uid = get_user_id()
    all_txs = stream_docs(sub(uid, 'registered_transactions'))
    accounts = []
    for a in stream_docs(sub(uid, 'registered_accounts')):
        acc = with_room(a, [t for t in all_txs if t.get('account_id') == a['_id']])
        acc.pop('years')
        accounts.append(acc)
    accounts.sort(key=lambda a: a.get('created_at', ''))
    types = [{'type': t, **{k: m[k] for k in ('label', 'name', 'kind', 'first_year')},
              'lifetime_limit': FHSA_LIFETIME_LIMIT if t == 'fhsa' else m.get('lifetime_limit')}
             for t, m in INVESTING_TYPES.items()]
    return jsonify({'accounts': accounts, 'year': current_year(), 'types': types})

@app.route('/api/registered', methods=['POST'])
@login_required
def api_create_registered():
    uid = get_user_id()
    fields, error = valid_registered_fields(request.get_json(silent=True) or {})
    if error:
        return jsonify({'error': error}), 400
    fields['created_at'] = now_iso()
    _, ref = sub(uid, 'registered_accounts').add(fields)
    return jsonify({'success': True, 'account': with_room({**fields, '_id': ref.id}, [])})

@app.route('/api/registered/<account_id>', methods=['GET'])
@login_required
def api_get_registered(account_id):
    uid = get_user_id()
    doc = sub(uid, 'registered_accounts').document(account_id).get()
    if not doc.exists:
        return jsonify({'error': 'Account not found.'}), 404
    txs = registered_transactions(uid, account_id)
    txs.sort(key=lambda t: (t.get('date', ''), t.get('created_at', '')), reverse=True)
    return jsonify({'account': with_room({**doc.to_dict(), '_id': account_id}, txs), 'transactions': txs})

@app.route('/api/registered/<account_id>', methods=['PUT'])
@login_required
def api_update_registered(account_id):
    uid = get_user_id()
    ref = sub(uid, 'registered_accounts').document(account_id)
    doc = ref.get()
    if not doc.exists:
        return jsonify({'error': 'Account not found.'}), 404
    fields, error = valid_registered_fields(request.get_json(silent=True) or {}, existing=doc.to_dict())
    if error:
        return jsonify({'error': error}), 400
    txs = registered_transactions(uid, account_id)
    if any((t.get('date') or '')[:4] < str(fields['start_year']) for t in txs):
        return jsonify({'error': 'Some logged transactions are before that start year. Delete them first.'}), 400
    ref.update(fields)
    return jsonify({'success': True, 'account': with_room({**ref.get().to_dict(), '_id': account_id}, txs)})

@app.route('/api/registered/<account_id>', methods=['DELETE'])
@login_required
def api_delete_registered(account_id):
    uid = get_user_id()
    ref = sub(uid, 'registered_accounts').document(account_id)
    if not ref.get().exists:
        return jsonify({'error': 'Account not found.'}), 404
    for t in registered_transactions(uid, account_id):
        sub(uid, 'registered_transactions').document(t['_id']).delete()
    ref.delete()
    return jsonify({'success': True})

@app.route('/api/registered/<account_id>/transactions', methods=['POST'])
@login_required
def api_add_registered_transaction(account_id):
    uid = get_user_id()
    doc = sub(uid, 'registered_accounts').document(account_id).get()
    if not doc.exists:
        return jsonify({'error': 'Account not found.'}), 404
    account = doc.to_dict()
    data = request.get_json(silent=True) or {}

    tx_type = data.get('type')
    if tx_type not in ('contribution', 'withdrawal'):
        return jsonify({'error': 'Choose contribution or withdrawal.'}), 400
    date = (data.get('date') or '').strip()
    try:
        tx_date = datetime.strptime(date, '%Y-%m-%d').date()
    except ValueError:
        return jsonify({'error': 'Enter a valid date.'}), 400
    if tx_date > datetime.now(timezone.utc).date():
        return jsonify({'error': "Date can't be in the future."}), 400
    if tx_date.year < int(account['start_year']):
        return jsonify({'error': f"Date can't be before {account['start_year']}, the year your starting room is from."}), 400
    try:
        amount = round(float(data.get('amount')), 2)
    except (TypeError, ValueError):
        return jsonify({'error': 'Amount must be a number.'}), 400
    if amount <= 0:
        return jsonify({'error': 'Amount must be more than $0.'}), 400

    tx = {'account_id': account_id, 'date': date, 'type': tx_type, 'amount': amount,
          'note': (data.get('note') or '').strip(), 'created_at': now_iso()}

    # US-20: warn before an over-contribution, but let the user go ahead —
    # it's allowed, it just costs a 1%/month penalty tax. Only warn when this
    # contribution makes things worse, so an account that's already over
    # doesn't nag on every unrelated entry.
    if tx_type == 'contribution' and data.get('force') is not True:
        txs = registered_transactions(uid, account_id)
        before = over_contribution(account, txs, tx_date.year, current_year())
        after = over_contribution(account, txs + [tx], tx_date.year, current_year())
        if after > before:
            return jsonify({
                'error': over_contribution_message(account, txs + [tx], after),
                'confirm_required': True,
                'over_by': after,
            }), 409

    _, ref = sub(uid, 'registered_transactions').add(tx)
    return jsonify({'success': True, 'transaction': {**tx, '_id': ref.id}})

@app.route('/api/registered/<account_id>/transactions/<tx_id>', methods=['DELETE'])
@login_required
def api_delete_registered_transaction(account_id, tx_id):
    uid = get_user_id()
    ref = sub(uid, 'registered_transactions').document(tx_id)
    doc = ref.get()
    if not doc.exists or doc.to_dict().get('account_id') != account_id:
        return jsonify({'error': 'Transaction not found.'}), 404
    ref.delete()
    return jsonify({'success': True})


# ===== AI assistant =====
# The model sees a snapshot of this user's data (assistant.py). Anything it
# wants to add comes back as a proposal: validated here with the same rules
# as the accounts APIs, then only created when the user confirms it in the UI.

ASSISTANT_UNAVAILABLE = ('The assistant needs the local AI model, and it isn\u2019t running right now. '
                         'Start it with `make ollama`, then try again.')

def assistant_proposal(action):
    """Turns the model's action into {endpoint, payload, summary}, or None."""
    kind = action.get('kind')
    name = str(action.get('name') or '').strip()[:80]
    acc_type = str(action.get('account_type') or '').strip().lower()
    institution = str(action.get('institution') or '').strip()[:80]
    try:
        amount = round(float(action.get('amount') or 0), 2)
    except (TypeError, ValueError):
        amount = 0.0

    if kind == 'add_bank_account':
        payload = {'name': name, 'type': acc_type, 'institution': institution, 'opening_balance': amount}
        if valid_account_fields(payload)[1]:
            return None
        amount_label = 'Balance owed' if acc_type == 'credit_card' else 'Current balance'
        return {'endpoint': '/api/accounts', 'payload': payload,
                'summary': {'title': name, 'type_label': acc_type.replace('_', ' ').capitalize(),
                            'institution': institution, 'amount_label': amount_label, 'amount': amount,
                            'view_url': '/accounts'}}

    if kind == 'add_investing_account':
        meta = INVESTING_TYPES.get(acc_type)
        if not meta:
            return None
        payload = {'name': name, 'type': acc_type, 'institution': institution, 'start_year': current_year()}
        amount_label = None
        if meta['kind'] == 'annual':
            payload['starting_room'] = amount
            amount_label = f'Room in {current_year()}'
        elif meta['kind'] == 'lifetime':
            payload['prior_contributions'] = amount
            amount_label = 'Contributed so far'
        if valid_registered_fields(payload)[1]:
            return None
        return {'endpoint': '/api/registered', 'payload': payload,
                'summary': {'title': name, 'type_label': f"{meta['label']} \u00b7 {meta['name']}",
                            'institution': institution, 'amount_label': amount_label,
                            'amount': amount if amount_label else None, 'view_url': '/investing'}}
    return None

@app.route('/api/assistant', methods=['POST'])
@login_required
def api_assistant():
    uid = get_user_id()
    history = assistant.clean_history((request.get_json(silent=True) or {}).get('messages'))
    if not history or history[-1]['role'] != 'user':
        return jsonify({'error': 'Ask a question first.'}), 400

    all_txs = stream_docs(sub(uid, 'registered_transactions'))
    investing = [with_room(a, [t for t in all_txs if t.get('account_id') == a['_id']])
                 for a in stream_docs(sub(uid, 'registered_accounts'))]
    now = datetime.now(timezone.utc)
    snapshot = assistant.build_snapshot(
        today=now.date(),
        user_name=session.get('user_name', ''),
        accounts=stream_docs(sub(uid, 'accounts')),
        investing_accounts=investing,
        budget_report=budget_report(uid, now.strftime('%Y-%m')),
        transactions=confirmed_transactions(uid, 'all'),
        categories_by_id=categories_by_id(),
        transfers_id=categories_by_name().get('Transfers', {}).get('_id'),
    )
    try:
        result = assistant.ask(history, snapshot, INVESTING_TYPES)
    except llm.LLMUnavailable:
        return jsonify({'error': ASSISTANT_UNAVAILABLE}), 503
    except llm.LLMError:
        return jsonify({'error': 'The assistant had trouble answering. Please try again.'}), 502
    return jsonify({'reply': result['reply'], 'proposal': assistant_proposal(result['action'])})

if __name__ == '__main__':
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    app.run(debug=True, port=5000)

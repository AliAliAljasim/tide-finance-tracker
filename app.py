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

reset_serializer = URLSafeTimedSerializer(app.config['SECRET_KEY'], salt='password-reset')

# ===== Optional HTTPS enforcement (NFR: "All pages served over HTTPS") =====
# Local dev has no TLS cert, so this only redirects when explicitly turned on
# (e.g. behind a reverse proxy that sets X-Forwarded-Proto). In production this
# would run behind a proxy/load balancer that terminates TLS and sets that header.

@app.before_request
def _enforce_https():
    if os.environ.get('FORCE_HTTPS') == '1' and request.headers.get('X-Forwarded-Proto', 'http') != 'https':
        return redirect(request.url.replace('http://', 'https://', 1), code=301)

# ===== Firestore-style helpers (see firestore_db.py / CLAUDE.md) =====

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
    return redirect(url_for('accounts_page') if 'user_id' in session else url_for('login'))

@app.route('/signup')
def signup():
    if 'user_id' in session:
        return redirect(url_for('accounts_page'))
    return render_template('signup.html')

@app.route('/login')
def login():
    if 'user_id' in session:
        return redirect(url_for('accounts_page'))
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
    return jsonify({'success': True})

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


if __name__ == '__main__':
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    app.run(debug=True, port=5000)

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

@app.errorhandler(413)
def too_large(e):
    if request.path.startswith('/api/'):
        return jsonify({'error': 'File is too large. The limit is 10 MB.'}), 413
    return 'File is too large. The limit is 10 MB.', 413

# ===== Page routes =====

@app.route('/')
def index():
    return redirect(url_for('upload_page') if 'user_id' in session else url_for('login'))

@app.route('/signup')
def signup():
    if 'user_id' in session:
        return redirect(url_for('upload_page'))
    return render_template('signup.html')

@app.route('/login')
def login():
    if 'user_id' in session:
        return redirect(url_for('upload_page'))
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
        'created_at': datetime.now(timezone.utc).isoformat(),
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

# ===== Accounts (US-04: "a simple account name/type is enough for Sprint 1") =====

@app.route('/api/accounts', methods=['GET'])
@login_required
def api_list_accounts():
    uid = get_user_id()
    return jsonify({'accounts': stream_docs(sub(uid, 'accounts'))})

@app.route('/api/accounts', methods=['POST'])
@login_required
def api_create_account():
    uid = get_user_id()
    data = request.get_json(silent=True) or {}
    name = (data.get('name') or '').strip()
    acc_type = (data.get('type') or 'Other').strip()
    if not name:
        return jsonify({'error': 'Account name is required.'}), 400
    _, ref = sub(uid, 'accounts').add({
        'name': name, 'type': acc_type, 'created_at': datetime.now(timezone.utc).isoformat(),
    })
    return jsonify({'success': True, 'account': {'_id': ref.id, 'name': name, 'type': acc_type}})

# ===== Statement upload & AI parsing pipeline (US-04, US-05, US-06) =====

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
        'created_at': datetime.now(timezone.utc).isoformat(),
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
        tx_sub.add({**tx, 'account_id': account_id, 'statement_id': statement_id})

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
    transactions = [t for t in stream_docs(sub(uid, 'transactions')) if t.get('statement_id') == statement_id]
    transactions.sort(key=lambda t: t.get('date', ''))
    return jsonify({'statement': statement, 'transactions': transactions})

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
        'account_id': stmt_doc.to_dict().get('account_id'),
        'statement_id': statement_id,
    }
    _, ref = sub(uid, 'transactions').add(tx)
    tx['_id'] = ref.id
    return jsonify({'success': True, 'transaction': tx})

@app.route('/api/statements/<statement_id>/transactions/<tx_id>', methods=['PUT'])
@login_required
def api_update_transaction(statement_id, tx_id):
    uid = get_user_id()
    ref = sub(uid, 'transactions').document(tx_id)
    if not ref.get().exists:
        return jsonify({'error': 'Transaction not found.'}), 404
    data = request.get_json(silent=True) or {}
    updates = {}
    for field in ('date', 'description', 'type'):
        if field in data:
            updates[field] = data[field]
    if 'amount' in data:
        updates['amount'] = float(data['amount'] or 0)
    if 'balance' in data:
        updates['balance'] = data['balance']
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
    transactions, balance_ok = validate_transactions(
        transactions, statement.get('opening_balance'), statement.get('closing_balance'),
        statement.get('period_start'), statement.get('period_end'),
    )
    tx_sub = sub(uid, 'transactions')
    for tx in transactions:
        tx_sub.document(tx['_id']).update({'flagged': tx['flagged'], 'flag_reason': tx['flag_reason']})

    # US-07: "Nothing is saved until the user clicks Confirm" — the rows were
    # already written so they're editable; confirming locks them in and, per
    # the privacy requirement, deletes the uploaded file.
    file_path = statement.get('file_path')
    if file_path and os.path.exists(file_path):
        os.remove(file_path)
    stmt_ref.update({'status': 'confirmed', 'balance_ok': balance_ok, 'confirmed_at': datetime.now(timezone.utc).isoformat()})
    return jsonify({'success': True})

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


if __name__ == '__main__':
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    app.run(debug=True, port=5000)

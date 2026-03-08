from flask import Flask, render_template, jsonify, request, session, redirect, url_for
from datetime import datetime, date
from werkzeug.security import generate_password_hash, check_password_hash
import json
import os
import io
import re
import yfinance as yf
from functools import wraps
import anthropic
import pdfplumber
from firestore_db import fs

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dev-finance-app-secret-key-change-in-production')
app.config['SESSION_TYPE'] = 'filesystem'
app.config['SESSION_PERMANENT'] = True
app.config['PERMANENT_SESSION_LIFETIME'] = 60 * 60 * 24 * 30  # 30 days
app.config['MAX_CONTENT_LENGTH'] = 15 * 1024 * 1024  # 15 MB upload limit

# ===== Firestore Helpers =====

def user_ref(uid):
    return fs.collection('users').document(uid)

def sub(uid, collection):
    return user_ref(uid).collection(collection)

def stream_docs(query):
    """Convert a Firestore stream to a list of dicts, each with '_id' set to the doc ID."""
    result = []
    for doc in query.stream():
        d = doc.to_dict() or {}
        d['_id'] = doc.id
        result.append(d)
    return result

def get_settings(uid):
    doc = sub(uid, 'settings').document('default').get()
    if doc.exists:
        return doc.to_dict()
    defaults = {
        'hourly_wage': 20.0,
        'hours_per_week': 20.0,
        'weeks_per_month': 4.33,
        'savings_target_percent': 0.65,
        'tfsa_lifetime_limit': 95000.0,
        'tfsa_yearly_limit': 7000.0,
        'fhsa_lifetime_limit': 40000.0,
        'fhsa_yearly_limit': 8000.0,
        'fhsa_open_year': None,
    }
    sub(uid, 'settings').document('default').set(defaults)
    return defaults

def monthly_income(settings):
    return settings.get('hourly_wage', 0) * settings.get('hours_per_week', 0) * settings.get('weeks_per_month', 4.33)

def account_balance(uid, account_name, starting_balance):
    txs = stream_docs(sub(uid, 'transactions').where('account', '==', account_name))
    income = sum(float(t.get('amount', 0)) for t in txs if t.get('type') == 'Income')
    expenses = sum(float(t.get('amount', 0)) for t in txs if t.get('type') == 'Expense')
    return float(starting_balance) + income - expenses

# ===== Statement Parsing Helpers =====

def extract_pdf_text(file_bytes):
    parts = []
    with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
        for page in pdf.pages:
            tables = page.extract_tables()
            if tables:
                for table in tables:
                    for row in table:
                        if row:
                            parts.append(' | '.join(str(cell or '').strip() for cell in row))
            else:
                text = page.extract_text()
                if text:
                    parts.append(text)
    return '\n'.join(parts)


def analyze_statement_with_claude(statement_text, categories, accounts):
    api_key = os.environ.get('ANTHROPIC_API_KEY')
    if not api_key:
        raise ValueError('ANTHROPIC_API_KEY environment variable is not set.')

    client = anthropic.Anthropic(api_key=api_key)
    categories_str = ', '.join(categories) if categories else 'Groceries, Dining, Transport, Entertainment, Bills, Other'
    accounts_str = ', '.join(accounts) if accounts else 'Chequing'

    if len(statement_text) > 50000:
        statement_text = statement_text[:50000] + '\n[truncated]'

    prompt = f"""You are a financial data extraction assistant for a Canadian personal finance app. Analyze the bank/credit card statement below.

User's expense categories: {categories_str}
User's accounts: {accounts_str}

Statement:
---
{statement_text}
---

Return ONLY a raw JSON object — no markdown, no code blocks, no explanation. Use this exact structure:
{{
  "month_key": "YYYY-MM",
  "transactions": [
    {{
      "date": "YYYY-MM-DD",
      "description": "clean short description",
      "amount": 0.00,
      "type": "Income",
      "category": "category name",
      "account": "account name"
    }}
  ],
  "diary": {{
    "overall_notes": "General summary of the month's financial picture",
    "next_month_focus": "Specific actionable recommendations for next month"
  }}
}}

Rules:
- All dates in YYYY-MM-DD format
- Amounts are always positive floats
- Debits/withdrawals/purchases → "Expense"; Credits/deposits/refunds → "Income"
- Skip internal transfers between own accounts
- Match category to one of the user's categories; use "Other" if none fit
- Match account to one of the user's accounts; default to the first account"""

    message = client.messages.create(
        model='claude-sonnet-4-6',
        max_tokens=4096,
        messages=[{'role': 'user', 'content': prompt}]
    )

    response_text = message.content[0].text.strip()
    response_text = re.sub(r'^```(?:json)?\s*', '', response_text, flags=re.MULTILINE)
    response_text = re.sub(r'\s*```\s*$', '', response_text, flags=re.MULTILINE)
    return json.loads(response_text.strip())

# ===== Auth & Helpers =====

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

def get_current_month_key():
    return datetime.now().strftime('%Y-%m')

def get_user_id():
    uid = session.get('user_id')
    return str(uid) if uid is not None else None

def parse_date(date_str):
    if isinstance(date_str, date):
        return date_str.isoformat() if not isinstance(date_str, datetime) else date_str.strftime('%Y-%m-%d')
    if not date_str:
        return datetime.now().strftime('%Y-%m-%d')
    try:
        return datetime.strptime(str(date_str)[:10], '%Y-%m-%d').strftime('%Y-%m-%d')
    except Exception:
        return datetime.now().strftime('%Y-%m-%d')

# ===== TFSA / FHSA Calculations =====

TFSA_ANNUAL_LIMITS = {
    2009: 5000, 2010: 5000, 2011: 5000, 2012: 5000,
    2013: 5500, 2014: 5500,
    2015: 10000,
    2016: 5500, 2017: 5500, 2018: 5500,
    2019: 6000, 2020: 6000, 2021: 6000, 2022: 6000,
    2023: 6500,
    2024: 7000, 2025: 7000, 2026: 7000,
}

def calculate_tfsa_lifetime_limit(dob_str, residency_str=None):
    try:
        dob = datetime.strptime(dob_str[:10], '%Y-%m-%d')
    except Exception:
        return 95000.0
    current_year = datetime.now().year
    start_year = max(dob.year + 18, 2009)
    if residency_str:
        try:
            res_year = datetime.strptime(residency_str[:10], '%Y-%m-%d').year
            start_year = max(start_year, res_year)
        except Exception:
            pass
    if start_year > current_year:
        return 0.0
    total = 0.0
    for year in range(start_year, current_year + 1):
        total += TFSA_ANNUAL_LIMITS.get(year, TFSA_ANNUAL_LIMITS[max(TFSA_ANNUAL_LIMITS.keys())])
    return total

FHSA_ANNUAL_LIMIT = 8000
FHSA_LIFETIME_CAP = 40000

def calculate_fhsa_room(open_year, deposits):
    """deposits: list of dicts with 'date' (YYYY-MM-DD) and 'amount' keys."""
    current_year = datetime.now().year
    if open_year > current_year:
        return 0.0
    by_year = {}
    for d in deposits:
        date_str = d.get('date', '') if isinstance(d, dict) else d.date.strftime('%Y-%m-%d')
        yr = int(date_str[:4]) if date_str else 0
        amount = float(d.get('amount', 0) if isinstance(d, dict) else d.amount)
        if yr:
            by_year[yr] = by_year.get(yr, 0.0) + amount
    carry = 0.0
    for year in range(open_year, current_year):
        year_room = min(FHSA_ANNUAL_LIMIT + carry, 2 * FHSA_ANNUAL_LIMIT)
        contributed = by_year.get(year, 0.0)
        unused = max(year_room - contributed, 0.0)
        carry = min(unused, FHSA_ANNUAL_LIMIT)
    current_year_room = min(FHSA_ANNUAL_LIMIT + carry, 2 * FHSA_ANNUAL_LIMIT)
    contributed_current_year = by_year.get(current_year, 0.0)
    room_now = max(current_year_room - contributed_current_year, 0.0)
    total_contributed = sum(by_year.values())
    lifetime_remaining = max(FHSA_LIFETIME_CAP - total_contributed, 0.0)
    return min(room_now, lifetime_remaining)

RRSP_MAX_BY_YEAR = {2023: 30780, 2024: 31560, 2025: 32490, 2026: 32490}

ACCOUNT_SLUG_MAP = {
    'tfsa': 'TFSA', 'rrsp': 'RRSP', 'fhsa': 'FHSA',
    'resp': 'RESP', 'non-registered': 'Non-Registered',
}

# ===== Page Routes =====

@app.route('/')
@login_required
def dashboard():
    return render_template('dashboard.html')

@app.route('/signup')
def signup():
    if 'user_id' in session:
        return redirect(url_for('dashboard'))
    return render_template('signup.html')

@app.route('/login')
def login():
    if 'user_id' in session:
        return redirect(url_for('dashboard'))
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

@app.route('/stocks')
@login_required
def stocks():
    return render_template('stocks.html', now=datetime.now())

@app.route('/investments/<account_slug>')
@login_required
def account_detail(account_slug):
    account_type = ACCOUNT_SLUG_MAP.get(account_slug.lower())
    if not account_type:
        return redirect(url_for('stocks'))
    return render_template('account.html', account_type=account_type, account_slug=account_slug.lower())

@app.route('/networth')
@login_required
def networth():
    return render_template('networth.html')

@app.route('/diary')
@login_required
def diary():
    return render_template('diary.html')

@app.route('/profile')
@login_required
def profile_page():
    uid = get_user_id()
    user = user_ref(uid).get().to_dict() or {}
    settings = get_settings(uid)
    financial_goals = user.get('financial_goals', [])
    registered_accounts = user.get('registered_accounts', [])

    goal_keyword_map = {
        'emergency-fund': ['emergency'],
        'debt-payoff':    ['debt', 'loan', 'credit'],
        'home-purchase':  ['home', 'house', 'fhsa', 'mortgage'],
        'retirement':     ['retire', 'rrsp', 'pension'],
        'investing':      ['invest', 'tfsa', 'stock', 'portfolio'],
        'travel':         ['travel', 'vacation', 'trip'],
        'education':      ['education', 'tuition', 'school', 'resp'],
    }
    user_goals = stream_docs(sub(uid, 'goals'))
    goal_titles_lower = [g.get('title', '').lower() for g in user_goals]

    info_fields = [
        ('Date of Birth',     bool(user.get('date_of_birth'))),
        ('Province',          bool(user.get('province'))),
        ('Life Stage',        bool(user.get('life_stage'))),
        ('Employment Status', bool(user.get('employment_status'))),
        ('Household Status',  bool(user.get('household_status'))),
    ]
    info_complete = sum(1 for _, d in info_fields if d)
    info_missing  = [n for n, d in info_fields if not d]

    income_fields = [
        ('Hourly Wage',         bool(settings.get('hourly_wage') and settings.get('hourly_wage', 0) > 0)),
        ('Financial Goals',     bool(financial_goals)),
        ('Registered Accounts', bool(registered_accounts)),
    ]
    income_complete = sum(1 for _, d in income_fields if d)
    income_missing  = [n for n, d in income_fields if not d]

    goals_fields = []
    for gt in financial_goals:
        keywords = goal_keyword_map.get(gt, [])
        matched = any(any(kw in title for kw in keywords) for title in goal_titles_lower)
        goals_fields.append((gt.replace('-', ' ').title(), matched))
    goals_complete = sum(1 for _, d in goals_fields if d)
    goals_missing  = [n for n, d in goals_fields if not d]

    total_complete = info_complete + income_complete + goals_complete
    total_items    = len(info_fields) + len(income_fields) + len(goals_fields)

    account_names = sorted(a.get('name', '') for a in stream_docs(sub(uid, 'accounts')))

    return render_template('profile.html',
        financial_goals=financial_goals,
        registered_accounts=registered_accounts,
        account_names=account_names,
        monthly_income=round(monthly_income(settings), 2),
        savings_target_amount=round(monthly_income(settings) * settings.get('savings_target_percent', 0.65), 2),
        savings_target_percent=round(settings.get('savings_target_percent', 0.65) * 100),
        total_complete=total_complete,
        total_items=total_items,
        info_complete=info_complete,
        info_total=len(info_fields),
        info_missing=info_missing,
        income_complete=income_complete,
        income_total=len(income_fields),
        income_missing=income_missing,
        goals_complete=goals_complete,
        goals_total=len(goals_fields),
        goals_missing=goals_missing,
    )

@app.route('/settings')
@login_required
def settings_page():
    uid = get_user_id()
    user = user_ref(uid).get().to_dict() or {}
    settings = get_settings(uid)
    financial_goals = user.get('financial_goals', [])
    registered_accounts = user.get('registered_accounts', [])
    province_map = {'AB':'Alberta','BC':'British Columbia','MB':'Manitoba','NB':'New Brunswick',
                    'NL':'Newfoundland & Labrador','NS':'Nova Scotia','NT':'Northwest Territories',
                    'NU':'Nunavut','ON':'Ontario','PE':'Prince Edward Island','QC':'Quebec',
                    'SK':'Saskatchewan','YT':'Yukon'}
    life_stage_map = {'student':'Student','early-career':'Early Career','mid-career':'Mid Career',
                      'pre-retirement':'Pre-Retirement','retired':'Retired'}
    employment_map = {'employed-full':'Employed Full-Time','employed-part':'Employed Part-Time',
                      'self-employed':'Self-Employed','unemployed':'Unemployed','student':'Student'}
    household_map  = {'single':'Single','married':'Married','common-law':'Common-Law',
                      'single-parent':'Single Parent','living-with-family':'Living With Family'}
    return render_template('settings.html',
        user=user, settings=settings,
        financial_goals=financial_goals,
        registered_accounts=registered_accounts,
        province_map=province_map,
        life_stage_map=life_stage_map,
        employment_map=employment_map,
        household_map=household_map)

# ===== Auth API =====

@app.route('/api/reset-password', methods=['POST'])
def reset_password():
    try:
        data = request.json
        email    = (data.get('email') or '').lower().strip()
        password = data.get('password', '')
        if not email or not password:
            return jsonify({'error': 'Email and password are required'}), 400
        if len(password) < 6:
            return jsonify({'error': 'Password must be at least 6 characters'}), 400

        users = list(fs.collection('users').where('email', '==', email).limit(1).stream())
        if not users:
            return jsonify({'error': 'No account found with that email'}), 404

        new_hash = generate_password_hash(password)
        fs.collection('users').document(users[0].id).update({'password_hash': new_hash})
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/login', methods=['POST'])
def login_user():
    try:
        data = request.json
        if not data.get('email') or not data.get('password'):
            return jsonify({'error': 'Missing email or password'}), 400

        users = list(fs.collection('users').where('email', '==', data['email'].lower().strip()).limit(1).stream())
        if not users:
            return jsonify({'error': 'Invalid email or password'}), 401

        user_doc = users[0]
        user = user_doc.to_dict()
        if not check_password_hash(user.get('password_hash', ''), data['password']):
            return jsonify({'error': 'Invalid email or password'}), 401

        session.permanent = True
        session['user_id'] = user_doc.id
        session['user_email'] = user.get('email')
        session['user_name'] = user.get('full_name')
        return jsonify({'success': True, 'message': 'Login successful'})

    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/signup', methods=['POST'])
def signup_account():
    try:
        data = request.json
        if not data.get('fullName') or not data.get('email') or not data.get('password'):
            return jsonify({'error': 'Missing required fields'}), 400

        email = data['email'].lower().strip()
        existing = list(fs.collection('users').where('email', '==', email).limit(1).stream())
        if existing:
            return jsonify({'error': 'Email already registered'}), 400

        personal_info = data.get('personalInfo', {})
        password_hash = generate_password_hash(data['password'])

        # Create user document
        _, user_doc_ref = fs.collection('users').add({
            'email': email,
            'password_hash': password_hash,
            'full_name': data['fullName'],
            'province': personal_info.get('province', ''),
            'life_stage': personal_info.get('lifeStage', ''),
            'employment_status': personal_info.get('employmentStatus', ''),
            'household_status': personal_info.get('householdStatus', ''),
            'financial_goals': personal_info.get('financialGoals', []),
            'registered_accounts': personal_info.get('registeredAccounts', []),
            'date_of_birth': None,
            'residency_date': None,
            'created_at': datetime.utcnow().isoformat(),
        })
        uid = user_doc_ref.id

        session.permanent = True
        session['user_id'] = uid
        session['user_email'] = email
        session['user_name'] = data['fullName']

        accounts_data = data.get('accounts', {})
        registered = personal_info.get('registeredAccounts', [])

        # Create accounts
        for name, key in [('Chequing', 'chequing'), ('Cash', 'cash'), ('TFSA', 'tfsa')]:
            sub(uid, 'accounts').add({'name': name, 'starting_balance': float(accounts_data.get(key, 0)), 'created_at': datetime.utcnow().isoformat()})
        for key, name in [('rrsp', 'RRSP'), ('resp', 'RESP'), ('fhsa', 'FHSA')]:
            if key in registered:
                sub(uid, 'accounts').add({'name': name, 'starting_balance': float(accounts_data.get(key, 0)), 'created_at': datetime.utcnow().isoformat()})

        # Budget categories
        budget_data = data.get('budget', {})
        default_categories = [
            ('Food & Groceries', budget_data.get('food', 500)),
            ('Transportation', budget_data.get('transport', 300)),
            ('Housing', budget_data.get('housing', 1500)),
            ('Entertainment', budget_data.get('entertainment', 200)),
            ('Utilities', budget_data.get('utilities', 150)),
            ('Shopping', budget_data.get('shopping', 250)),
        ]
        for cat_name, budget_amt in default_categories:
            sub(uid, 'categories').add({'name': cat_name, 'monthly_budget': float(budget_amt), 'created_at': datetime.utcnow().isoformat()})

        # Settings
        sub(uid, 'settings').document('default').set({
            'hourly_wage': 20.0, 'hours_per_week': 20.0, 'weeks_per_month': 4.33,
            'savings_target_percent': 0.65, 'tfsa_lifetime_limit': 95000.0,
            'tfsa_yearly_limit': 7000.0, 'fhsa_lifetime_limit': 40000.0,
            'fhsa_yearly_limit': 8000.0, 'fhsa_open_year': None,
        })

        # Initial TFSA deposit
        tfsa_bal = float(accounts_data.get('tfsa', 0))
        if tfsa_bal > 0:
            sub(uid, 'tfsa_deposits').add({
                'date': datetime.now().strftime('%Y-%m-%d'),
                'amount': tfsa_bal,
                'note': 'Initial balance from signup',
                'created_at': datetime.utcnow().isoformat(),
            })

        # Initial net worth snapshot
        month_key = get_current_month_key()
        chequing_bal = float(accounts_data.get('chequing', 0))
        cash_bal = float(accounts_data.get('cash', 0))
        sub(uid, 'networth_snapshots').document(month_key).set({
            'month_key': month_key,
            'chequing': chequing_bal, 'cash': cash_bal,
            'tfsa': tfsa_bal, 'total': chequing_bal + cash_bal + tfsa_bal,
            'created_at': datetime.utcnow().isoformat(),
        })

        return jsonify({'success': True, 'message': 'Account setup completed successfully'})

    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ===== Dashboard =====

@app.route('/api/dashboard-data')
@login_required
def get_dashboard_data():
    try:
        uid = get_user_id()
        settings = get_settings(uid)
        month_key = get_current_month_key()

        txs = stream_docs(sub(uid, 'transactions').where('month_key', '==', month_key))
        total_income = sum(float(t.get('amount', 0)) for t in txs if t.get('type') == 'Income')
        total_expenses = sum(float(t.get('amount', 0)) for t in txs if t.get('type') == 'Expense')

        chequing_bal = 0
        cash_bal = 0
        for acct in stream_docs(sub(uid, 'accounts')):
            if acct.get('name') == 'Chequing':
                chequing_bal = account_balance(uid, 'Chequing', acct.get('starting_balance', 0))
            elif acct.get('name') == 'Cash':
                cash_bal = account_balance(uid, 'Cash', acct.get('starting_balance', 0))

        holdings = stream_docs(sub(uid, 'holdings'))
        tfsa_value = sum(float(h.get('total_shares', 0)) * float(h.get('current_price', 0)) for h in holdings)
        tfsa_book = sum(float(h.get('total_shares', 0)) * float(h.get('avg_cost', 0)) for h in holdings)

        tfsa_deposits = stream_docs(sub(uid, 'tfsa_deposits'))
        tfsa_contributed = sum(float(d.get('amount', 0)) for d in tfsa_deposits)

        return jsonify({
            'dashboard': {
                'monthKey': month_key,
                'monthlyIncome': monthly_income(settings),
                'totalIncome': total_income,
                'totalExpenses': total_expenses,
                'netMonth': total_income - total_expenses,
                'netWorth': chequing_bal + cash_bal + tfsa_value,
            },
            'accounts': {'chequing': chequing_bal, 'cash': cash_bal, 'tfsa': tfsa_value},
            'tfsa': {'value': tfsa_value, 'contributed': tfsa_contributed, 'gain': tfsa_value - tfsa_book},
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/spending-breakdown')
@login_required
def get_spending_breakdown():
    try:
        uid = get_user_id()
        month_key = get_current_month_key()
        categories = stream_docs(sub(uid, 'categories'))
        txs = stream_docs(sub(uid, 'transactions').where('month_key', '==', month_key).where('type', '==', 'Expense'))

        by_cat = {}
        for t in txs:
            c = t.get('category', '')
            by_cat[c] = by_cat.get(c, 0) + float(t.get('amount', 0))

        result = []
        for cat in categories:
            name = cat.get('name', '')
            budget = float(cat.get('monthly_budget', 0))
            spent = by_cat.get(name, 0)
            result.append({'name': name, 'spent': spent, 'budget': budget, 'percentUsed': (spent / budget) if budget > 0 else 0})
        return jsonify({'categories': result})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/form-options')
@login_required
def get_form_options():
    try:
        uid = get_user_id()
        categories = sorted(c.get('name', '') for c in stream_docs(sub(uid, 'categories')))
        accounts = sorted(a.get('name', '') for a in stream_docs(sub(uid, 'accounts')))
        return jsonify({'categories': categories, 'accounts': accounts})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/transactions/month/<month_key>')
@login_required
def get_transactions_by_month(month_key):
    try:
        uid = get_user_id()
        txs = stream_docs(sub(uid, 'transactions').where('month_key', '==', month_key))
        txs.sort(key=lambda t: t.get('date', ''), reverse=True)
        result = [{'id': t['_id'], 'date': t.get('date', ''), 'name': t.get('name', ''),
                   'category': t.get('category', ''), 'account': t.get('account', ''),
                   'type': t.get('type', ''), 'amount': float(t.get('amount', 0))} for t in txs]
        return jsonify({'success': True, 'transactions': result})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/recent-transactions')
@login_required
def get_recent_transactions():
    try:
        uid = get_user_id()
        txs = stream_docs(sub(uid, 'transactions'))
        txs.sort(key=lambda t: t.get('date', ''), reverse=True)
        result = [{'date': t.get('date', ''), 'name': t.get('name', ''), 'category': t.get('category', ''),
                   'account': t.get('account', ''), 'type': t.get('type', ''), 'amount': float(t.get('amount', 0))}
                  for t in txs[:10]]
        return jsonify({'transactions': result})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/networth-history')
@login_required
def get_networth_history():
    try:
        uid = get_user_id()
        snapshots = stream_docs(sub(uid, 'networth_snapshots'))
        snapshots.sort(key=lambda s: s.get('month_key', ''))
        history = [{'monthKey': s.get('month_key', ''), 'total': float(s.get('total', 0)),
                    'net_deposits': float(s.get('net_deposits', 0))}
                   for s in snapshots]
        return jsonify({'history': history})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/avg-spending')
@login_required
def get_avg_spending():
    try:
        uid = get_user_id()
        year = str(datetime.now().year)
        txs = stream_docs(sub(uid, 'transactions').where('type', '==', 'Expense'))
        by_month = {}
        for t in txs:
            mk = t.get('month_key', '')
            if mk.startswith(year + '-'):
                by_month[mk] = by_month.get(mk, 0) + float(t.get('amount', 0))
        if not by_month:
            return jsonify({'average': 0, 'months': 0})
        total = sum(by_month.values())
        return jsonify({'average': round(total / len(by_month), 2), 'months': len(by_month)})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ===== Add Transaction =====

@app.route('/api/add-transaction', methods=['POST'])
@login_required
def add_transaction():
    try:
        uid = get_user_id()
        data = request.json
        tx_date = parse_date(data.get('date'))
        _, ref = sub(uid, 'transactions').add({
            'date': tx_date,
            'name': data.get('name', ''),
            'category': data.get('category', ''),
            'account': data.get('account', ''),
            'type': data.get('type', 'Expense'),
            'amount': float(data.get('amount', 0)),
            'month_key': tx_date[:7],
            'created_at': datetime.utcnow().isoformat(),
        })
        return jsonify({'success': True, 'id': ref.id})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ===== Net Worth Snapshot =====

@app.route('/api/create-networth-snapshot', methods=['POST'])
@login_required
def create_networth_snapshot():
    try:
        uid = get_user_id()
        month_key = get_current_month_key()

        chequing_bal = 0
        cash_bal = 0
        for acct in stream_docs(sub(uid, 'accounts')):
            if acct.get('name') == 'Chequing':
                chequing_bal = account_balance(uid, 'Chequing', acct.get('starting_balance', 0))
            elif acct.get('name') == 'Cash':
                cash_bal = account_balance(uid, 'Cash', acct.get('starting_balance', 0))

        holdings = stream_docs(sub(uid, 'holdings'))
        tfsa_val = sum(float(h.get('total_shares', 0)) * float(h.get('current_price', 0)) for h in holdings)
        total = chequing_bal + cash_bal + tfsa_val

        # Net deposits = starting balances of all accounts + cumulative income up to this month
        all_accounts = stream_docs(sub(uid, 'accounts'))
        starting_total = sum(float(a.get('starting_balance', 0)) for a in all_accounts)
        all_income = stream_docs(sub(uid, 'transactions').where('type', '==', 'Income'))
        cumulative_income = sum(
            float(t.get('amount', 0)) for t in all_income
            if t.get('month_key', '') <= month_key
        )
        net_deposits = starting_total + cumulative_income

        sub(uid, 'networth_snapshots').document(month_key).set({
            'month_key': month_key, 'chequing': chequing_bal, 'cash': cash_bal,
            'tfsa': tfsa_val, 'total': total, 'net_deposits': net_deposits,
            'created_at': datetime.utcnow().isoformat(),
        })
        return jsonify({'success': True, 'month_key': month_key})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ===== Investment Accounts =====

@app.route('/api/investment-accounts')
@login_required
def get_investment_accounts():
    try:
        uid = get_user_id()
        user = user_ref(uid).get().to_dict() or {}
        settings = get_settings(uid)
        registered = user.get('registered_accounts', [])

        accounts = []
        for key in ['tfsa', 'rrsp', 'resp', 'fhsa']:
            if key in registered:
                label = ACCOUNT_SLUG_MAP[key]
                accounts.append({'key': label, 'label': label})

        registered_lower = [a.lower() for a in registered]
        has_non_reg = 'non-registered' in registered_lower or \
            any(h.get('account_type') == 'Non-Registered' for h in stream_docs(sub(uid, 'holdings')))
        if has_non_reg:
            accounts.append({'key': 'Non-Registered', 'label': 'Non-Registered'})

        fhsa_needs_open_year = 'fhsa' in registered and not settings.get('fhsa_open_year')
        return jsonify({'accounts': accounts, 'fhsaNeedsOpenYear': fhsa_needs_open_year})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/account-detail/<account_slug>')
@login_required
def get_account_detail(account_slug):
    try:
        account_type = ACCOUNT_SLUG_MAP.get(account_slug.lower())
        if not account_type:
            return jsonify({'error': 'Unknown account type'}), 404

        uid = get_user_id()
        current_year = datetime.now().year

        holdings_docs = stream_docs(sub(uid, 'holdings').where('account_type', '==', account_type))
        holdings_data = [{
            'id': h['_id'], 'ticker': h.get('ticker', ''), 'name': h.get('name', ''),
            'totalShares': float(h.get('total_shares', 0)), 'avgCost': float(h.get('avg_cost', 0)),
            'price': float(h.get('current_price', 0)),
            'marketValue': float(h.get('total_shares', 0)) * float(h.get('current_price', 0)),
            'bookValue': float(h.get('total_shares', 0)) * float(h.get('avg_cost', 0)),
            'gainLoss': float(h.get('total_shares', 0)) * (float(h.get('current_price', 0)) - float(h.get('avg_cost', 0))),
        } for h in holdings_docs]

        user = user_ref(uid).get().to_dict() or {}
        settings = get_settings(uid)

        if account_type == 'TFSA':
            dob = user.get('date_of_birth')
            if dob:
                lifetime_limit = calculate_tfsa_lifetime_limit(dob, user.get('residency_date'))
            else:
                lifetime_limit = settings.get('tfsa_lifetime_limit', 95000.0)
            annual_limit = TFSA_ANNUAL_LIMITS.get(current_year, 7000)
            deposits = stream_docs(sub(uid, 'tfsa_deposits'))
            total_contributed = sum(float(d.get('amount', 0)) for d in deposits)
            contrib_info = {
                'type': 'TFSA', 'hasTracking': True,
                'lifetimeLimit': lifetime_limit, 'annualLimit': annual_limit,
                'contributed': total_contributed, 'room': lifetime_limit - total_contributed,
                'description': 'Tax-Free Savings Account',
                'detail': f'Annual limit for {current_year}: ${annual_limit:,.0f}. Contributions are not tax-deductible, but growth and withdrawals are tax-free.',
            }

        elif account_type == 'FHSA':
            open_year = settings.get('fhsa_open_year')
            if not open_year:
                contrib_info = {'type': 'FHSA', 'hasTracking': False, 'needsOpenYear': True, 'description': 'First Home Savings Account'}
            else:
                deposits = stream_docs(sub(uid, 'fhsa_deposits'))
                total_contributed = sum(float(d.get('amount', 0)) for d in deposits)
                room_available = calculate_fhsa_room(int(open_year), deposits)
                contrib_info = {
                    'type': 'FHSA', 'hasTracking': True, 'needsOpenYear': False,
                    'lifetimeLimit': FHSA_LIFETIME_CAP, 'contributed': total_contributed,
                    'room': room_available, 'openYear': open_year,
                    'description': 'First Home Savings Account',
                    'detail': f'$8,000/year since {open_year} (max $16,000 in a single year with carry-forward) | Lifetime limit: $40,000.',
                }

        elif account_type == 'RRSP':
            annual_max = RRSP_MAX_BY_YEAR.get(current_year, 32490)
            contrib_info = {
                'type': 'RRSP', 'hasTracking': False, 'annualMax': annual_max,
                'description': 'Registered Retirement Savings Plan',
                'detail': f'{current_year} maximum: ${annual_max:,.0f}. Your personal room is 18% of your {current_year - 1} earned income.',
            }

        elif account_type == 'RESP':
            contrib_info = {
                'type': 'RESP', 'hasTracking': False, 'lifetimeLimit': 50000,
                'annualCESGOptimal': 2500, 'cesgRate': 20, 'cesgMax': 500, 'cesgLifetimeMax': 7200,
                'description': 'Registered Education Savings Plan',
                'detail': 'Lifetime limit: $50,000 per beneficiary. CESG contributes 20% on first $2,500/year (up to $500/year, $7,200 lifetime).',
            }

        else:
            contrib_info = {
                'type': account_type, 'hasTracking': False, 'description': 'Non-Registered Account',
                'detail': 'No contribution limits apply. Investment income is taxable in the year earned.',
            }

        return jsonify({'holdings': holdings_data, 'contributionInfo': contrib_info})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/tfsa-summary')
@login_required
def get_tfsa_summary():
    try:
        uid = get_user_id()
        user = user_ref(uid).get().to_dict() or {}
        settings = get_settings(uid)

        holdings = stream_docs(sub(uid, 'holdings'))
        tfsa_market_value = sum(float(h.get('total_shares', 0)) * float(h.get('current_price', 0)) for h in holdings)
        tfsa_book_value   = sum(float(h.get('total_shares', 0)) * float(h.get('avg_cost', 0))     for h in holdings)

        deposits = stream_docs(sub(uid, 'tfsa_deposits'))
        tfsa_contributed = sum(float(d.get('amount', 0)) for d in deposits)

        dob = user.get('date_of_birth')
        if dob:
            lifetime_limit = calculate_tfsa_lifetime_limit(dob, user.get('residency_date'))
        else:
            lifetime_limit = settings.get('tfsa_lifetime_limit', 95000)

        current_year = datetime.now().year
        yearly_limit = TFSA_ANNUAL_LIMITS.get(current_year, TFSA_ANNUAL_LIMITS[max(TFSA_ANNUAL_LIMITS.keys())])

        return jsonify({
            'marketValue': tfsa_market_value, 'totalContributed': tfsa_contributed,
            'gainLoss': tfsa_market_value - tfsa_book_value,
            'lifetimeLimit': lifetime_limit, 'remainingRoom': lifetime_limit - tfsa_contributed,
            'yearlyLimit': float(yearly_limit),
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ===== TFSA Deposits =====

@app.route('/api/tfsa-deposits')
@login_required
def get_tfsa_deposits():
    try:
        uid = get_user_id()
        deps = stream_docs(sub(uid, 'tfsa_deposits'))
        deps.sort(key=lambda d: d.get('date', ''), reverse=True)
        return jsonify({'deposits': [{'date': d.get('date', ''), 'amount': float(d.get('amount', 0)),
                                      'note': d.get('note', ''), 'row': d['_id']} for d in deps]})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/add-tfsa-deposit', methods=['POST'])
@login_required
def add_tfsa_deposit():
    try:
        uid = get_user_id()
        data = request.json
        _, ref = sub(uid, 'tfsa_deposits').add({
            'date': parse_date(data.get('date')), 'amount': float(data.get('amount', 0)),
            'note': data.get('note', ''), 'created_at': datetime.utcnow().isoformat(),
        })
        return jsonify({'success': True, 'row': ref.id})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/update-tfsa-deposit/<deposit_id>', methods=['PUT'])
@login_required
def update_tfsa_deposit(deposit_id):
    try:
        uid = get_user_id()
        data = request.json
        doc_ref = sub(uid, 'tfsa_deposits').document(deposit_id)
        doc = doc_ref.get()
        if not doc.exists:
            return jsonify({'error': 'Deposit not found'}), 404
        existing = doc.to_dict()
        doc_ref.update({
            'date': parse_date(data.get('date', existing.get('date'))),
            'amount': float(data.get('amount', existing.get('amount', 0))),
            'note': data.get('note', existing.get('note', '')),
        })
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/delete-tfsa-deposit/<deposit_id>', methods=['DELETE'])
@login_required
def delete_tfsa_deposit(deposit_id):
    try:
        uid = get_user_id()
        doc_ref = sub(uid, 'tfsa_deposits').document(deposit_id)
        if not doc_ref.get().exists:
            return jsonify({'error': 'Deposit not found'}), 404
        doc_ref.delete()
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ===== TFSA Trades =====

@app.route('/api/tfsa-trades')
@login_required
def get_tfsa_trades():
    try:
        uid = get_user_id()
        trades = stream_docs(sub(uid, 'tfsa_trades'))
        trades.sort(key=lambda t: t.get('date', ''), reverse=True)
        return jsonify({'trades': [{'date': t.get('date', ''), 'ticker': t.get('ticker', ''),
                                    'shares': float(t.get('shares', 0)), 'costPerShare': float(t.get('cost_per_share', 0)),
                                    'fees': float(t.get('fees', 0)), 'totalCost': float(t.get('total_cost', 0)),
                                    'row': t['_id']} for t in trades]})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/add-tfsa-trade', methods=['POST'])
@login_required
def add_tfsa_trade():
    try:
        uid = get_user_id()
        data = request.json
        shares = float(data.get('shares', 0))
        cost_per_share = float(data.get('costPerShare', 0))
        fees = float(data.get('fees', 0))
        total_cost = (shares * cost_per_share) + fees
        ticker = data.get('ticker', '').upper()
        account_type = data.get('accountType', 'TFSA')

        _, ref = sub(uid, 'tfsa_trades').add({
            'date': parse_date(data.get('date')), 'ticker': ticker,
            'shares': shares, 'cost_per_share': cost_per_share,
            'fees': fees, 'total_cost': total_cost,
            'created_at': datetime.utcnow().isoformat(),
        })

        # Upsert holding
        holding_id = f'{ticker}_{account_type}'
        holding_ref = sub(uid, 'holdings').document(holding_id)
        holding_doc = holding_ref.get()
        if holding_doc.exists:
            h = holding_doc.to_dict()
            existing_shares = float(h.get('total_shares', 0))
            existing_cost = existing_shares * float(h.get('avg_cost', 0))
            new_total_shares = existing_shares + shares
            new_avg_cost = (existing_cost + total_cost) / new_total_shares if new_total_shares > 0 else 0
            holding_ref.update({'total_shares': new_total_shares, 'avg_cost': new_avg_cost})
        else:
            holding_ref.set({
                'ticker': ticker, 'name': data.get('name', ''), 'account_type': account_type,
                'total_shares': shares, 'avg_cost': cost_per_share,
                'current_price': 0.0, 'last_price_update': None,
                'created_at': datetime.utcnow().isoformat(),
            })

        return jsonify({'success': True, 'row': ref.id})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/update-tfsa-trade/<trade_id>', methods=['PUT'])
@login_required
def update_tfsa_trade(trade_id):
    try:
        uid = get_user_id()
        doc_ref = sub(uid, 'tfsa_trades').document(trade_id)
        doc = doc_ref.get()
        if not doc.exists:
            return jsonify({'error': 'Trade not found'}), 404
        existing = doc.to_dict()
        data = request.json
        new_shares = float(data.get('shares', existing.get('shares', 0)))
        new_cps    = float(data.get('costPerShare', existing.get('cost_per_share', 0)))
        new_fees   = float(data.get('fees', existing.get('fees', 0)))
        doc_ref.update({
            'date': parse_date(data.get('date', existing.get('date'))),
            'ticker': data.get('ticker', existing.get('ticker', '')).upper(),
            'shares': new_shares, 'cost_per_share': new_cps, 'fees': new_fees,
            'total_cost': (new_shares * new_cps) + new_fees,
        })
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/delete-tfsa-trade/<trade_id>', methods=['DELETE'])
@login_required
def delete_tfsa_trade(trade_id):
    try:
        uid = get_user_id()
        doc_ref = sub(uid, 'tfsa_trades').document(trade_id)
        if not doc_ref.get().exists:
            return jsonify({'error': 'Trade not found'}), 404
        doc_ref.delete()
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ===== FHSA Deposits =====

@app.route('/api/fhsa-deposits')
@login_required
def get_fhsa_deposits():
    try:
        uid = get_user_id()
        deps = stream_docs(sub(uid, 'fhsa_deposits'))
        deps.sort(key=lambda d: d.get('date', ''), reverse=True)
        return jsonify({'deposits': [{'date': d.get('date', ''), 'amount': float(d.get('amount', 0)),
                                      'note': d.get('note', ''), 'row': d['_id']} for d in deps]})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/add-fhsa-deposit', methods=['POST'])
@login_required
def add_fhsa_deposit():
    try:
        uid = get_user_id()
        data = request.json
        _, ref = sub(uid, 'fhsa_deposits').add({
            'date': parse_date(data.get('date')), 'amount': float(data.get('amount', 0)),
            'note': data.get('note', ''), 'created_at': datetime.utcnow().isoformat(),
        })
        return jsonify({'success': True, 'row': ref.id})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/update-fhsa-deposit/<deposit_id>', methods=['PUT'])
@login_required
def update_fhsa_deposit(deposit_id):
    try:
        uid = get_user_id()
        doc_ref = sub(uid, 'fhsa_deposits').document(deposit_id)
        doc = doc_ref.get()
        if not doc.exists:
            return jsonify({'error': 'Deposit not found'}), 404
        existing = doc.to_dict()
        data = request.json
        doc_ref.update({
            'date': parse_date(data.get('date', existing.get('date'))),
            'amount': float(data.get('amount', existing.get('amount', 0))),
            'note': data.get('note', existing.get('note', '')),
        })
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/delete-fhsa-deposit/<deposit_id>', methods=['DELETE'])
@login_required
def delete_fhsa_deposit(deposit_id):
    try:
        uid = get_user_id()
        doc_ref = sub(uid, 'fhsa_deposits').document(deposit_id)
        if not doc_ref.get().exists:
            return jsonify({'error': 'Deposit not found'}), 404
        doc_ref.delete()
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ===== Holdings =====

@app.route('/api/tfsa-holdings')
@login_required
def get_tfsa_holdings():
    try:
        uid = get_user_id()
        holdings = stream_docs(sub(uid, 'holdings'))
        result = [{
            'ticker': h.get('ticker', ''), 'name': h.get('name', ''),
            'accountType': h.get('account_type', 'TFSA'),
            'totalShares': float(h.get('total_shares', 0)), 'avgCost': float(h.get('avg_cost', 0)),
            'price': float(h.get('current_price', 0)),
            'marketValue': float(h.get('total_shares', 0)) * float(h.get('current_price', 0)),
            'bookValue':   float(h.get('total_shares', 0)) * float(h.get('avg_cost', 0)),
            'gainLoss':    float(h.get('total_shares', 0)) * (float(h.get('current_price', 0)) - float(h.get('avg_cost', 0))),
            'row': h['_id'],
        } for h in holdings]
        return jsonify({'holdings': result})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/add-holding', methods=['POST'])
@login_required
def add_holding():
    try:
        uid = get_user_id()
        data = request.json
        ticker = data.get('ticker', '').upper()
        account_type = data.get('accountType', 'TFSA')
        holding_id = f'{ticker}_{account_type}'
        doc_ref = sub(uid, 'holdings').document(holding_id)
        doc_ref.set({
            'ticker': ticker, 'name': data.get('name', ''), 'account_type': account_type,
            'total_shares': float(data.get('shares', 0)), 'avg_cost': float(data.get('avgCost', 0)),
            'current_price': 0.0, 'last_price_update': None,
            'created_at': datetime.utcnow().isoformat(),
        })
        return jsonify({'success': True, 'row': holding_id})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/update-holding/<holding_id>', methods=['PUT'])
@login_required
def update_holding(holding_id):
    try:
        uid = get_user_id()
        doc_ref = sub(uid, 'holdings').document(holding_id)
        doc = doc_ref.get()
        if not doc.exists:
            return jsonify({'error': 'Holding not found'}), 404
        existing = doc.to_dict()
        data = request.json
        updates = {
            'ticker': data.get('ticker', existing.get('ticker', '')).upper(),
            'name': data.get('name', existing.get('name', '')),
            'total_shares': float(data.get('shares', existing.get('total_shares', 0))),
            'avg_cost': float(data.get('avgCost', existing.get('avg_cost', 0))),
        }
        if 'accountType' in data:
            updates['account_type'] = data['accountType']
        doc_ref.update(updates)
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/delete-holding/<holding_id>', methods=['DELETE'])
@login_required
def delete_holding(holding_id):
    try:
        uid = get_user_id()
        doc_ref = sub(uid, 'holdings').document(holding_id)
        if not doc_ref.get().exists:
            return jsonify({'error': 'Holding not found'}), 404
        doc_ref.delete()
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/delete-account/<account_type>', methods=['DELETE'])
@login_required
def delete_account(account_type):
    try:
        uid = get_user_id()
        # Delete all holdings for this account type
        for h in stream_docs(sub(uid, 'holdings').where('account_type', '==', account_type)):
            sub(uid, 'holdings').document(h['_id']).delete()
        # Remove from registered_accounts
        user = user_ref(uid).get().to_dict() or {}
        registered = [a for a in user.get('registered_accounts', []) if a.lower() != account_type.lower()]
        user_ref(uid).update({'registered_accounts': registered})
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ===== Price Updates =====

def update_holding_prices(uid):
    holdings = stream_docs(sub(uid, 'holdings'))
    if not holdings:
        return
    now = datetime.now()
    to_update = []
    for h in holdings:
        last = h.get('last_price_update')
        if last:
            try:
                last_dt = datetime.fromisoformat(last)
                if (now - last_dt).total_seconds() <= 300:
                    continue
            except Exception:
                pass
        to_update.append(h)
    if not to_update:
        return
    symbols = [h.get('ticker') for h in to_update]
    try:
        data = yf.download(symbols, period='1d', progress=False, threads=False)
        if not data.empty:
            for h in to_update:
                ticker = h.get('ticker')
                try:
                    price = float(data['Close'].iloc[-1] if len(symbols) == 1 else data['Close'][ticker].iloc[-1])
                    sub(uid, 'holdings').document(h['_id']).update({
                        'current_price': price, 'last_price_update': now.isoformat()
                    })
                except (KeyError, IndexError):
                    pass
    except Exception as e:
        print(f'Price update error: {e}')


def _price_update_loop():
    import threading, time
    while True:
        time.sleep(300)
        try:
            for user_doc in fs.collection('users').stream():
                update_holding_prices(user_doc.id)
        except Exception as e:
            print(f'Background price loop error: {e}')

# ===== Diary =====

@app.route('/api/diary/<month_key>')
@login_required
def get_diary(month_key):
    try:
        uid = get_user_id()
        doc = sub(uid, 'diary').document(month_key).get()
        if doc.exists:
            d = doc.to_dict()
            return jsonify({'success': True, 'diary': d})
        return jsonify({'success': False, 'diary': None})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/diary', methods=['POST'])
@login_required
def save_diary():
    try:
        uid = get_user_id()
        data = request.json
        month_key = data.get('month_key')
        doc_ref = sub(uid, 'diary').document(month_key)
        existing = doc_ref.get()
        payload = {
            'month_key': month_key,
            'overall_notes': data.get('overall_notes', ''),
            'next_month_focus': data.get('next_month_focus', ''),
            'mood_rating': data.get('mood_rating', 0),
            'updated_at': datetime.utcnow().isoformat(),
        }
        if existing.exists:
            doc_ref.update(payload)
        else:
            payload['created_at'] = datetime.utcnow().isoformat()
            doc_ref.set(payload)
        return jsonify({'success': True, 'month_key': month_key})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/diary/list')
@login_required
def list_diaries():
    try:
        uid = get_user_id()
        diaries = stream_docs(sub(uid, 'diary'))
        diaries.sort(key=lambda d: d.get('month_key', ''), reverse=True)
        result = [{'month_key': d.get('month_key', ''), 'updated_at': d.get('updated_at', '')[:10]} for d in diaries]
        return jsonify({'success': True, 'diaries': result})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/diary/parse-statement', methods=['POST'])
@login_required
def parse_statement():
    try:
        if not os.environ.get('ANTHROPIC_API_KEY'):
            return jsonify({'error': 'Claude API key not configured. Set the ANTHROPIC_API_KEY environment variable.'}), 400
        if 'file' not in request.files:
            return jsonify({'error': 'No file uploaded.'}), 400
        file = request.files['file']
        if not file.filename:
            return jsonify({'error': 'No file selected.'}), 400

        filename = file.filename.lower()
        file_bytes = file.read()

        if filename.endswith('.pdf'):
            statement_text = extract_pdf_text(file_bytes)
        elif filename.endswith('.csv'):
            statement_text = file_bytes.decode('utf-8', errors='replace')
        else:
            return jsonify({'error': 'Unsupported format. Please upload a PDF or CSV file.'}), 400

        if not statement_text.strip():
            return jsonify({'error': 'Could not extract text from the file.'}), 400

        uid = get_user_id()
        user_categories = [c.get('name', '') for c in stream_docs(sub(uid, 'categories'))]
        user_accounts   = [a.get('name', '') for a in stream_docs(sub(uid, 'accounts'))]

        result = analyze_statement_with_claude(statement_text, user_categories, user_accounts)
        return jsonify({'success': True, 'data': result})
    except json.JSONDecodeError:
        return jsonify({'error': 'Claude returned an unexpected response. Please try again.'}), 500
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/diary/import-statement', methods=['POST'])
@login_required
def import_statement():
    try:
        uid = get_user_id()
        data = request.json
        month_key = data.get('month_key')
        transactions = data.get('transactions', [])

        imported = 0
        for tx in transactions:
            if not tx.get('selected', True):
                continue
            sub(uid, 'transactions').add({
                'date': tx['date'],
                'name': tx['description'],
                'category': tx.get('category', 'Other'),
                'account': tx.get('account', ''),
                'type': tx['type'],
                'amount': float(tx['amount']),
                'month_key': tx['date'][:7],
                'created_at': datetime.utcnow().isoformat(),
            })
            imported += 1

        return jsonify({'success': True, 'imported': imported, 'month_key': month_key})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ===== Profile & Settings =====

@app.route('/api/profile')
@login_required
def get_profile():
    try:
        uid = get_user_id()
        user = user_ref(uid).get().to_dict() or {}
        return jsonify({
            'fullName': user.get('full_name', ''),
            'email': user.get('email', ''),
            'province': user.get('province', ''),
            'lifeStage': user.get('life_stage', ''),
            'employmentStatus': user.get('employment_status', ''),
            'householdStatus': user.get('household_status', ''),
            'financialGoals': user.get('financial_goals', []),
            'registeredAccounts': user.get('registered_accounts', []),
            'createdAt': user.get('created_at', ''),
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/profile/update', methods=['POST'])
@login_required
def update_profile():
    try:
        uid = get_user_id()
        data = request.json
        updates = {}
        if data.get('fullName'):
            updates['full_name'] = data['fullName'].strip()
            session['user_name'] = updates['full_name']
        if data.get('email'):
            new_email = data['email'].strip().lower()
            existing = list(fs.collection('users').where('email', '==', new_email).limit(1).stream())
            if existing and existing[0].id != uid:
                return jsonify({'error': 'Email already in use'}), 400
            updates['email'] = new_email
            session['user_email'] = new_email
        if data.get('dateOfBirth'):
            updates['date_of_birth'] = parse_date(data['dateOfBirth'])
        for field, key in [('province', 'province'), ('lifeStage', 'life_stage'),
                           ('employmentStatus', 'employment_status'), ('householdStatus', 'household_status')]:
            if data.get(field):
                updates[key] = data[field]
        if updates:
            user_ref(uid).update(updates)
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/profile/password', methods=['POST'])
@login_required
def update_password():
    try:
        uid = get_user_id()
        user = user_ref(uid).get().to_dict() or {}
        data = request.json
        if not check_password_hash(user.get('password_hash', ''), data.get('currentPassword', '')):
            return jsonify({'error': 'Current password is incorrect'}), 400
        new_pw = data.get('newPassword', '')
        if len(new_pw) < 6:
            return jsonify({'error': 'Password must be at least 6 characters'}), 400
        user_ref(uid).update({'password_hash': generate_password_hash(new_pw)})
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/settings/update', methods=['POST'])
@login_required
def update_settings():
    try:
        uid = get_user_id()
        data = request.json
        settings_updates = {}
        user_updates = {}

        for key, field in [('hourlyWage','hourly_wage'), ('hoursPerWeek','hours_per_week'),
                           ('weeksPerMonth','weeks_per_month'), ('savingsTargetPercent','savings_target_percent'),
                           ('tfsaYearlyLimit','tfsa_yearly_limit'), ('tfsaLifetimeLimit','tfsa_lifetime_limit'),
                           ('fhsaYearlyLimit','fhsa_yearly_limit'), ('fhsaLifetimeLimit','fhsa_lifetime_limit')]:
            if key in data:
                settings_updates[field] = float(data[key])
        if 'fhsaOpenYear' in data:
            settings_updates['fhsa_open_year'] = int(data['fhsaOpenYear'])
        if 'financialGoals' in data:
            user_updates['financial_goals'] = data['financialGoals']
        if 'registeredAccounts' in data:
            user_updates['registered_accounts'] = data['registeredAccounts']

        if settings_updates:
            sub(uid, 'settings').document('default').set(settings_updates, merge=True)
        if user_updates:
            user_ref(uid).update(user_updates)
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ===== Goals =====

@app.route('/api/goals', methods=['GET'])
@login_required
def get_goals():
    try:
        uid = get_user_id()
        goals = stream_docs(sub(uid, 'goals'))
        goals.sort(key=lambda g: g.get('created_at', ''))
        return jsonify([{
            'id': g['_id'], 'title': g.get('title', ''), 'goalType': g.get('goal_type', 'target'),
            'icon': g.get('icon', 'fa-bullseye'), 'color': g.get('color', '#2563eb'),
            'targetAmount': float(g.get('target_amount', 0)), 'currentAmount': float(g.get('current_amount', 0)),
            'deadline': g.get('deadline'), 'monthlyContribution': float(g.get('monthly_contribution', 0)),
            'contributionFrequency': g.get('contribution_frequency'),
            'streakCount': g.get('streak_count', 0), 'lastCheckIn': g.get('last_check_in'),
            'account': g.get('account'),
        } for g in goals])
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/goals', methods=['POST'])
@login_required
def create_goal():
    try:
        uid = get_user_id()
        data = request.json
        _, ref = sub(uid, 'goals').add({
            'title': data.get('title', 'New Goal'), 'icon': data.get('icon', 'fa-bullseye'),
            'color': data.get('color', '#2563eb'), 'goal_type': data.get('goalType', 'target'),
            'target_amount': float(data.get('targetAmount', 0)),
            'current_amount': float(data.get('currentAmount', 0)),
            'deadline': parse_date(data['deadline']) if data.get('deadline') else None,
            'monthly_contribution': float(data.get('monthlyContribution', 0)),
            'contribution_frequency': data.get('contributionFrequency') or None,
            'account': data.get('account') or None,
            'streak_count': 0, 'last_check_in': None,
            'created_at': datetime.utcnow().isoformat(),
            'updated_at': datetime.utcnow().isoformat(),
        })
        return jsonify({'id': ref.id, 'success': True}), 201
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/goals/<goal_id>', methods=['PUT'])
@login_required
def update_goal(goal_id):
    try:
        uid = get_user_id()
        doc_ref = sub(uid, 'goals').document(goal_id)
        if not doc_ref.get().exists:
            return jsonify({'error': 'Goal not found'}), 404
        data = request.json
        updates = {'updated_at': datetime.utcnow().isoformat()}
        for key, field in [('title','title'), ('icon','icon'), ('color','color'), ('goalType','goal_type'),
                           ('contributionFrequency','contribution_frequency'), ('account','account')]:
            if key in data:
                updates[field] = data[key] or None
        for key, field in [('targetAmount','target_amount'), ('currentAmount','current_amount'), ('monthlyContribution','monthly_contribution')]:
            if key in data:
                updates[field] = float(data[key])
        if 'deadline' in data:
            updates['deadline'] = parse_date(data['deadline']) if data['deadline'] else None
        doc_ref.update(updates)
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/goals/<goal_id>', methods=['DELETE'])
@login_required
def delete_goal(goal_id):
    try:
        uid = get_user_id()
        doc_ref = sub(uid, 'goals').document(goal_id)
        if not doc_ref.get().exists:
            return jsonify({'error': 'Goal not found'}), 404
        doc_ref.delete()
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/goals/<goal_id>/checkin', methods=['POST'])
@login_required
def checkin_goal(goal_id):
    try:
        uid = get_user_id()
        doc_ref = sub(uid, 'goals').document(goal_id)
        doc = doc_ref.get()
        if not doc.exists:
            return jsonify({'error': 'Goal not found'}), 404
        g = doc.to_dict()
        period_days = {'weekly': 7, 'biweekly': 14, 'monthly': 30, 'quarterly': 90, 'yearly': 365}
        days = period_days.get(g.get('contribution_frequency') or 'monthly', 30)
        today = datetime.now().strftime('%Y-%m-%d')
        last_check_in = g.get('last_check_in')
        streak = g.get('streak_count', 0)
        if last_check_in:
            from datetime import date as date_type
            days_since = (date_type.fromisoformat(today) - date_type.fromisoformat(last_check_in[:10])).days
            if days_since < 1:
                return jsonify({'streakCount': streak, 'alreadyDone': True})
            elif days_since <= days:
                streak += 1
            else:
                streak = 1
        else:
            streak = 1
        doc_ref.update({'streak_count': streak, 'last_check_in': today, 'updated_at': datetime.utcnow().isoformat()})
        return jsonify({'success': True, 'streakCount': streak, 'lastCheckIn': today})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ===== Account Questionnaire =====

@app.route('/api/account-questionnaire', methods=['POST'])
@login_required
def save_account_questionnaire():
    try:
        uid = get_user_id()
        data = request.json
        user_updates = {}

        if data.get('dateOfBirth'):
            user_updates['date_of_birth'] = parse_date(data['dateOfBirth'])
        if data.get('residentBefore18'):
            user_updates['residency_date'] = None
        elif data.get('residencyDate'):
            user_updates['residency_date'] = parse_date(data['residencyDate'])

        if user_updates:
            user_ref(uid).update(user_updates)

        for h in data.get('holdings', []):
            ticker = h.get('ticker', '').strip().upper()
            if not ticker:
                continue
            holding_id = f'{ticker}_TFSA'
            sub(uid, 'holdings').document(holding_id).set({
                'ticker': ticker, 'name': h.get('name', ''), 'account_type': 'TFSA',
                'total_shares': float(h.get('shares', 0)), 'avg_cost': float(h.get('avgCost', 0)),
                'current_price': 0.0, 'last_price_update': None,
                'created_at': datetime.utcnow().isoformat(),
            }, merge=True)

        return jsonify({'success': True, 'message': 'Account details saved successfully'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ===== Ticker Search =====

def search_static_tickers(query):
    try:
        tickers_file = os.path.join(os.path.dirname(__file__), 'tickers.json')
        with open(tickers_file, 'r') as f:
            all_tickers = json.load(f)
        return [t for t in all_tickers if query in t['symbol'].upper() or query in t['name'].upper()][:20]
    except Exception:
        return []

def search_live_ticker(symbol):
    try:
        ticker = yf.Ticker(symbol)
        info = ticker.info
        if info and 'symbol' in info:
            ticker_type = 'Stock'
            qt = info.get('quoteType', '')
            if qt == 'ETF': ticker_type = 'ETF'
            elif qt == 'CRYPTOCURRENCY': ticker_type = 'Crypto'
            elif qt == 'MUTUALFUND': ticker_type = 'Fund'
            return {'symbol': info.get('symbol', symbol).upper(),
                    'name': info.get('longName') or info.get('shortName', 'N/A'),
                    'type': ticker_type, 'exchange': info.get('exchange', 'N/A')}
    except Exception:
        pass
    return None

@app.route('/api/tickers/search')
def search_tickers():
    try:
        query = request.args.get('q', '').strip().upper()
        if not query:
            return jsonify({'tickers': []})
        results = list(search_static_tickers(query))
        has_suffix = '.' in query
        if has_suffix:
            live = search_live_ticker(query)
            if live and not any(r['symbol'] == live['symbol'] for r in results):
                results.insert(0, live)
        if not has_suffix and len(query) <= 6 and len(results) < 5:
            for suffix in ['', '.TO', '.V', '.CN', '.L', '.AX', '.HK', '.T', '.DE', '.PA']:
                symbol = query + suffix if suffix else query
                live = search_live_ticker(symbol)
                if live and not any(r['symbol'] == live['symbol'] for r in results):
                    results.append(live)
                    if len(results) >= 20:
                        break
        seen, unique = set(), []
        for t in results:
            if t['symbol'] not in seen:
                seen.add(t['symbol'])
                unique.append(t)
                if len(unique) >= 20:
                    break
        return jsonify({'tickers': unique})
    except Exception as e:
        try:
            return jsonify({'tickers': search_static_tickers(request.args.get('q', '').upper())})
        except Exception:
            return jsonify({'error': str(e)}), 500

@app.route('/api/tickers/validate/<ticker>')
def validate_ticker(ticker):
    try:
        symbol = ticker.strip().upper()
        tickers_file = os.path.join(os.path.dirname(__file__), 'tickers.json')
        with open(tickers_file, 'r') as f:
            all_tickers = json.load(f)
        for t in all_tickers:
            if t['symbol'].upper() == symbol:
                return jsonify({'valid': True, 'ticker': t})
        live = search_live_ticker(symbol)
        if live:
            return jsonify({'valid': True, 'ticker': live})
        return jsonify({'valid': False})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/tickers/all')
def get_all_tickers():
    try:
        tickers_file = os.path.join(os.path.dirname(__file__), 'tickers.json')
        with open(tickers_file, 'r') as f:
            return jsonify({'tickers': json.load(f)})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ===== Main =====

if __name__ == '__main__':
    import threading
    t = threading.Thread(target=_price_update_loop, daemon=True)
    t.start()

    def _initial_update():
        import time
        time.sleep(2)
        try:
            for user_doc in fs.collection('users').stream():
                update_holding_prices(user_doc.id)
        except Exception as e:
            print(f'Initial price update error: {e}')

    threading.Thread(target=_initial_update, daemon=True).start()
    app.run(debug=True, port=5000)

"""Fill a user's account with realistic sample data for demos.

Adds bank accounts, three months of confirmed statements (Aug-Oct 2026 plus
early November on the credit card), one statement waiting for review, and
investing accounts with contributions. November spending is set up so the
budget alerts show: Groceries over its limit and Dining past 80%.

Every document it creates is tagged `sample: True`, so it can be removed
again without touching anything else:

    .venv/bin/python scripts/seed_demo_data.py --email you@example.com
    .venv/bin/python scripts/seed_demo_data.py --email you@example.com --remove

Stop the app first (`make down`): the server keeps the data file in memory
and would overwrite changes made while it runs.
"""
import argparse
import os
import random
import sys
from datetime import date, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import app as appmod  # noqa: E402
from categorization import normalize_merchant  # noqa: E402
from firestore_db import fs  # noqa: E402

TODAY = date(2026, 11, 3)
MONTHS = [(2026, 8), (2026, 9), (2026, 10)]
rng = random.Random(2026)

# (description, category, low, high) pools for card spending
CARD_POOLS = {
    'Groceries': (['LOBLAWS #1042', 'NO FRILLS #3381', 'METRO #224', 'FRESHCO #87'], 38, 115, 4),
    'Dining': (['TIM HORTONS #3301', 'STARBUCKS #4410', 'PAI NORTHERN THAI', 'UBER EATS', 'CHIPOTLE #2291', 'A&W #1180'], 6, 62, 6),
    'Transportation': (['UBER *TRIP', 'SHELL #5521'], 16, 58, 2),
    'Shopping': (['AMAZON.CA', 'UNIQLO EATON CENTRE', 'SHOPPERS DRUG MART #811'], 18, 85, 2),
    'Entertainment': (['CINEPLEX ODEON', 'STEAM PURCHASE'], 14, 38, 1),
}
CARD_FIXED = [  # (day, description, category, amount)
    (1, 'PRESTO AUTO-LOAD', 'Transportation', 50.00),
    (1, 'SPOTIFY P1F2A', 'Subscriptions', 11.99),
    (2, 'NETFLIX.COM', 'Subscriptions', 16.49),
    (9, 'APPLE.COM/BILL ICLOUD', 'Subscriptions', 3.99),
]
# Early November on the card: Groceries $42.18 (over a $30 budget),
# Dining $269.00 (90% of $300), Subscriptions, Transportation, Shopping.
CARD_NOVEMBER = [
    ('2026-11-01', 'PRESTO AUTO-LOAD', 'Transportation', 50.00),
    ('2026-11-01', 'SPOTIFY P1F2A', 'Subscriptions', 11.99),
    ('2026-11-01', 'STARBUCKS #4410', 'Dining', 6.45),
    ('2026-11-01', 'DINNER - ALO RESTAURANT', 'Dining', 148.00),
    ('2026-11-02', 'NETFLIX.COM', 'Subscriptions', 16.49),
    ('2026-11-02', 'LOBLAWS #1042', 'Groceries', 42.18),
    ('2026-11-02', 'SUSHI KAJI', 'Dining', 78.50),
    ('2026-11-03', 'UBER EATS', 'Dining', 31.20),
    ('2026-11-03', 'TIM HORTONS #3301', 'Dining', 4.85),
    ('2026-11-03', 'AMAZON.CA', 'Shopping', 34.99),
]


def month_days(y, m):
    start = date(y, m, 1)
    end = (date(y + (m == 12), m % 12 + 1, 1) - timedelta(days=1))
    return start, end


def find_user(email):
    for u in appmod.stream_docs(fs.collection('users')):
        if u.get('email') == email.lower():
            return u['_id']
    sys.exit(f'No user with email {email}')


def remove(uid):
    counts = {}
    for coll in ('transactions', 'statements', 'accounts', 'registered_transactions', 'registered_accounts'):
        for d in appmod.stream_docs(appmod.sub(uid, coll)):
            if d.get('sample'):
                appmod.sub(uid, coll).document(d['_id']).delete()
                counts[coll] = counts.get(coll, 0) + 1
    for acc in appmod.stream_docs(appmod.sub(uid, 'accounts')):
        appmod.recompute_account_balance(uid, acc['_id'])
    print('Removed sample documents:', counts or 'none')


def add_statement(uid, account, rows, period_start, period_end, status='confirmed', filename=None):
    """rows: [(iso_date, description, category, amount, 'debit'|'credit')], posted in date order."""
    cats = appmod.categories_by_name()
    owed = account['type'] == 'credit_card'
    rows = sorted(rows, key=lambda r: r[0])
    opening = account['running']
    running = opening
    created = f'{period_end}T18:00:00+00:00'
    _, sref = appmod.sub(uid, 'statements').add({
        'account_id': account['_id'], 'original_filename': filename or f"{account['name']} {period_end[:7]}.pdf",
        'file_path': None, 'period_start': period_start, 'period_end': period_end, 'status': status,
        'created_at': created, 'sample': True,
    })
    for d, desc, cat, amount, kind in rows:
        sign = 1 if kind == 'credit' else -1
        running = round(running + (-sign if owed else sign) * amount, 2)
        appmod.sub(uid, 'transactions').add({
            'date': d, 'description': desc, 'amount': round(amount, 2), 'type': kind, 'balance': running,
            'flagged': False, 'flag_reason': '', 'merchant_key': normalize_merchant(desc),
            'category_id': cats[cat]['_id'], 'is_duplicate': False, 'account_id': account['_id'],
            'statement_id': sref.id, 'confirmed': status == 'confirmed', 'sample': True,
        })
    update = {'opening_balance': opening, 'closing_balance': running, 'balance_ok': True}
    if status == 'confirmed':
        update['confirmed_at'] = created
        account['running'] = running
    appmod.sub(uid, 'statements').document(sref.id).update(update)
    return running


def card_month_rows(y, m):
    rows = []
    start, end = month_days(y, m)
    for cat, (names, lo, hi, n) in CARD_POOLS.items():
        for _ in range(n):
            day = start + timedelta(days=rng.randrange((end - start).days + 1))
            rows.append((day.isoformat(), rng.choice(names), cat, round(rng.uniform(lo, hi), 2), 'debit'))
    for day, desc, cat, amount in CARD_FIXED:
        rows.append((date(y, m, day).isoformat(), desc, cat, amount, 'debit'))
    return rows


def seed(uid):
    accounts = appmod.stream_docs(appmod.sub(uid, 'accounts'))
    if any(a.get('sample') for a in accounts):
        print('Sample data is already loaded; nothing to add (use --remove to clear it).')
        return

    def make_account(name, acc_type, institution, opening):
        fields = {'name': name, 'type': acc_type, 'institution': institution, 'opening_balance': opening,
                  'current_balance': opening, 'created_at': f'{MONTHS[0][0]}-0{MONTHS[0][1] - 1}-20T12:00:00+00:00',
                  'sample': True}
        _, ref = appmod.sub(uid, 'accounts').add(fields)
        return {**fields, '_id': ref.id, 'running': opening}

    chequing = next((a for a in accounts if a.get('type') == 'chequing'), None)
    if chequing:
        chequing['running'] = float(chequing.get('opening_balance') or 0)
    else:
        chequing = make_account('Everyday Chequing', 'chequing', 'TD', 3200.00)
    card = make_account('TD Cash Back Visa', 'credit_card', 'TD', 0.00)
    savings = make_account('EQ Bank Savings Plus', 'savings', 'EQ Bank', 4000.00)

    card_totals = {}
    for y, m in MONTHS:
        start, end = month_days(y, m)
        rows = card_month_rows(y, m)
        prev = card_totals.get((y, m - 1), 0)
        if prev:  # paying off last month's card balance from chequing
            rows.append((date(y, m, 22).isoformat(), 'PAYMENT - THANK YOU', 'Transfers', prev, 'credit'))
        card_totals[(y, m)] = round(sum(r[3] for r in rows if r[4] == 'debit'), 2)
        add_statement(uid, card, rows, start.isoformat(), end.isoformat())

        cheq_rows = [
            (date(y, m, 1).isoformat(), 'RENT E-TRANSFER - LANDLORD', 'Rent / Mortgage', 1450.00, 'debit'),
            (date(y, m, 12).isoformat(), 'HYDRO ONE', 'Utilities', round(rng.uniform(78, 112), 2), 'debit'),
            (date(y, m, 15).isoformat(), 'PAYROLL DEPOSIT - NORTHWIND LTD', 'Salary', 2150.00, 'credit'),
            (date(y, m, 16).isoformat(), 'TRANSFER TO EQ SAVINGS', 'Transfers', 300.00, 'debit'),
            (date(y, m, 20).isoformat(), 'ROGERS WIRELESS', 'Utilities', 65.00, 'debit'),
            (end.isoformat(), 'PAYROLL DEPOSIT - NORTHWIND LTD', 'Salary', 2150.00, 'credit'),
        ]
        if prev:
            cheq_rows.append((date(y, m, 22).isoformat(), 'TD VISA PAYMENT', 'Transfers', prev, 'debit'))
        if m == 9:
            cheq_rows.append((date(y, m, 25).isoformat(), 'CRA GST/HST CREDIT', 'Refund', 129.75, 'credit'))
        add_statement(uid, chequing, cheq_rows, start.isoformat(), end.isoformat())

        add_statement(uid, savings, [
            (date(y, m, 16).isoformat(), 'TRANSFER FROM TD CHEQUING', 'Transfers', 300.00, 'credit'),
            (end.isoformat(), 'INTEREST PAID', 'Investment income', round(rng.uniform(11, 15), 2), 'credit'),
        ], start.isoformat(), end.isoformat())

    # November so far: the card is confirmed (drives the budget alerts) and
    # the chequing statement is parsed but waiting for review.
    nov_rows = [(d, desc, cat, amt, 'debit') for d, desc, cat, amt in CARD_NOVEMBER]
    nov_rows.append(('2026-11-03', 'PAYMENT - THANK YOU', 'Transfers', card_totals[(2026, 10)], 'credit'))
    add_statement(uid, card, nov_rows, '2026-11-01', TODAY.isoformat())
    add_statement(uid, chequing, [
        ('2026-11-01', 'RENT E-TRANSFER - LANDLORD', 'Rent / Mortgage', 1450.00, 'debit'),
        ('2026-11-03', 'TD VISA PAYMENT', 'Transfers', card_totals[(2026, 10)], 'debit'),
        ('2026-11-03', 'GOODLIFE FITNESS', 'Health', 54.99, 'debit'),
    ], '2026-11-01', TODAY.isoformat(), status='parsed', filename='TD Chequing November.pdf')

    for acc in (chequing, card, savings):
        appmod.recompute_account_balance(uid, acc['_id'])

    seed_investing(uid)
    print('Sample data added. Accounts:',
          ', '.join(f"{a['name']} ({appmod.sub(uid, 'accounts').document(a['_id']).get().to_dict()['current_balance']:,.2f})"
                    for a in (chequing, card, savings)))


def seed_investing(uid):
    existing = appmod.stream_docs(appmod.sub(uid, 'registered_accounts'))

    def account(acc_type, name, institution, **fields):
        found = next((a for a in existing if a.get('type') == acc_type), None)
        if found:
            return found['_id']
        doc = {'type': acc_type, 'name': name, 'institution': institution, 'start_year': 2026,
               'starting_room': 0.0, 'prior_contributions': 0.0, 'annual_room': 0.0,
               'created_at': '2026-01-05T12:00:00+00:00', 'sample': True, **fields}
        _, ref = appmod.sub(uid, 'registered_accounts').add(doc)
        return ref.id

    def log(account_id, iso_date, amount, kind='contribution', note=''):
        appmod.sub(uid, 'registered_transactions').add({
            'account_id': account_id, 'date': iso_date, 'type': kind, 'amount': amount, 'note': note,
            'created_at': f'{iso_date}T12:00:00+00:00', 'sample': True})

    tfsa = account('tfsa', 'Questrade TFSA', 'Questrade', starting_room=7000.0)
    log(tfsa, '2026-01-15', 2500.00, note='New year top-up')
    log(tfsa, '2026-06-03', 1500.00, note='Bonus')  # $3,000 room left: logging $3,500+ shows the warning

    fhsa = account('fhsa', 'First Home FHSA', 'EQ Bank', starting_room=16000.0, prior_contributions=8000.0)
    log(fhsa, '2026-03-02', 3000.00)
    log(fhsa, '2026-09-01', 3000.00)

    rrsp = account('rrsp', 'Workplace RRSP', 'Sun Life', starting_room=18400.0, annual_room=12600.0)
    for month in range(1, 11):
        log(rrsp, f'2026-{month:02d}-15', 650.00, note='Payroll deduction')

    resp = account('resp', 'Sam’s RESP', 'TD', prior_contributions=12500.0)
    for month in range(1, 11):
        log(resp, f'2026-{month:02d}-05', 150.00)

    brokerage = account('non_registered', 'Wealthsimple Brokerage', 'Wealthsimple')
    log(brokerage, '2026-02-10', 2000.00)
    log(brokerage, '2026-07-21', 400.00, kind='withdrawal', note='Trip')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--email', required=True)
    parser.add_argument('--remove', action='store_true', help='delete everything this script added')
    args = parser.parse_args()
    uid = find_user(args.email)
    remove(uid) if args.remove else seed(uid)

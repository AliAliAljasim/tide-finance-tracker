"""
migrate_to_firestore.py
Migrates all data from the SQLite database (instance/finances.db) into Firestore.
Run once: python migrate_to_firestore.py
"""
import sqlite3
import json
import os
from datetime import datetime
from firestore_db import fs

DB_PATH = os.path.join(os.path.dirname(__file__), 'instance', 'finances.db')

def safe_json(val):
    """Parse a JSON string field or return the value as-is if already a list/dict."""
    if val is None:
        return []
    if isinstance(val, (list, dict)):
        return val
    try:
        return json.loads(val)
    except Exception:
        return []

def migrate():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    # Maps old SQLite integer user ID → new Firestore string doc ID
    uid_map = {}

    # ── Users ────────────────────────────────────────────────────────────────
    print("Migrating users...")
    cur.execute("SELECT * FROM users")
    for row in cur.fetchall():
        r = dict(row)
        old_id = r['id']

        doc_data = {
            'email':               r['email'],
            'password_hash':       r['password_hash'],
            'full_name':           r['full_name'] or '',
            'province':            r['province'] or '',
            'life_stage':          r['life_stage'] or '',
            'employment_status':   r['employment_status'] or '',
            'household_status':    r['household_status'] or '',
            'financial_goals':     safe_json(r['financial_goals']),
            'registered_accounts': safe_json(r['registered_accounts']),
            'date_of_birth':       r['date_of_birth'],
            'years_in_canada':     r['years_in_canada'],
            'residency_date':      r['residency_date'],
            'created_at':          r['created_at'],
        }

        # Check if this email already exists in Firestore
        existing = list(fs.collection('users').where('email', '==', r['email']).limit(1).stream())
        if existing:
            new_uid = existing[0].id
            print(f"  User {r['email']} already exists as {new_uid}, updating...")
            fs.collection('users').document(new_uid).update(doc_data)
        else:
            _, new_ref = fs.collection('users').add(doc_data)
            new_uid = new_ref.id
            print(f"  Created user {r['email']} → {new_uid}")

        uid_map[old_id] = new_uid

    # ── Settings ─────────────────────────────────────────────────────────────
    print("Migrating settings...")
    cur.execute("SELECT * FROM settings")
    for row in cur.fetchall():
        r = dict(row)
        uid = uid_map.get(r['user_id'])
        if not uid:
            continue
        fs.collection('users').document(uid).collection('settings').document('default').set({
            'hourly_wage':            float(r['hourly_wage'] or 20),
            'hours_per_week':         float(r['hours_per_week'] or 20),
            'weeks_per_month':        float(r['weeks_per_month'] or 4.33),
            'savings_target_percent': float(r['savings_target_percent'] or 0.65),
            'tfsa_lifetime_limit':    float(r['tfsa_lifetime_limit'] or 95000),
            'tfsa_yearly_limit':      float(r['tfsa_yearly_limit'] or 7000),
            'fhsa_lifetime_limit':    float(r['fhsa_lifetime_limit'] or 40000),
            'fhsa_yearly_limit':      float(r['fhsa_yearly_limit'] or 8000),
            'fhsa_open_year':         r['fhsa_open_year'],
            'created_at':             r['created_at'],
            'updated_at':             r['updated_at'],
        })
    print(f"  Done ({cur.rowcount} rows)")

    # ── Categories ───────────────────────────────────────────────────────────
    print("Migrating categories...")
    cur.execute("SELECT * FROM categories")
    count = 0
    for row in cur.fetchall():
        r = dict(row)
        uid = uid_map.get(r['user_id'])
        if not uid:
            continue
        fs.collection('users').document(uid).collection('categories').add({
            'name':           r['name'],
            'monthly_budget': float(r['monthly_budget'] or 0),
            'created_at':     r['created_at'],
        })
        count += 1
    print(f"  Done ({count} rows)")

    # ── Accounts ─────────────────────────────────────────────────────────────
    print("Migrating accounts...")
    cur.execute("SELECT * FROM accounts")
    count = 0
    for row in cur.fetchall():
        r = dict(row)
        uid = uid_map.get(r['user_id'])
        if not uid:
            continue
        fs.collection('users').document(uid).collection('accounts').add({
            'name':             r['name'],
            'starting_balance': float(r['starting_balance'] or 0),
            'created_at':       r['created_at'],
        })
        count += 1
    print(f"  Done ({count} rows)")

    # ── Transactions ─────────────────────────────────────────────────────────
    print("Migrating transactions...")
    cur.execute("SELECT * FROM transactions")
    count = 0
    for row in cur.fetchall():
        r = dict(row)
        uid = uid_map.get(r['user_id'])
        if not uid:
            continue
        fs.collection('users').document(uid).collection('transactions').add({
            'date':       r['date'],
            'name':       r['name'],
            'category':   r['category'],
            'account':    r['account'],
            'type':       r['type'],
            'amount':     float(r['amount'] or 0),
            'month_key':  r['month_key'],
            'created_at': r['created_at'],
        })
        count += 1
    print(f"  Done ({count} rows)")

    # ── Holdings ─────────────────────────────────────────────────────────────
    print("Migrating holdings...")
    cur.execute("SELECT * FROM holdings")
    count = 0
    for row in cur.fetchall():
        r = dict(row)
        uid = uid_map.get(r['user_id'])
        if not uid:
            continue
        doc_id = f"{r['ticker']}_{r['account_type']}"
        fs.collection('users').document(uid).collection('holdings').document(doc_id).set({
            'ticker':            r['ticker'],
            'name':              r['name'] or '',
            'total_shares':      float(r['total_shares'] or 0),
            'avg_cost':          float(r['avg_cost'] or 0),
            'current_price':     float(r['current_price'] or 0),
            'account_type':      r['account_type'],
            'last_price_update': r['last_price_update'],
            'created_at':        r['created_at'],
            'updated_at':        r['updated_at'],
        })
        count += 1
    print(f"  Done ({count} rows)")

    # ── TFSA Deposits ─────────────────────────────────────────────────────────
    print("Migrating TFSA deposits...")
    cur.execute("SELECT * FROM tfsa_deposits")
    count = 0
    for row in cur.fetchall():
        r = dict(row)
        uid = uid_map.get(r['user_id'])
        if not uid:
            continue
        fs.collection('users').document(uid).collection('tfsa_deposits').add({
            'date':       r['date'],
            'amount':     float(r['amount'] or 0),
            'note':       r['note'] or '',
            'created_at': r['created_at'],
        })
        count += 1
    print(f"  Done ({count} rows)")

    # ── TFSA Trades ───────────────────────────────────────────────────────────
    print("Migrating TFSA trades...")
    cur.execute("SELECT * FROM tfsa_trades")
    count = 0
    for row in cur.fetchall():
        r = dict(row)
        uid = uid_map.get(r['user_id'])
        if not uid:
            continue
        fs.collection('users').document(uid).collection('tfsa_trades').add({
            'date':           r['date'],
            'ticker':         r['ticker'],
            'shares':         float(r['shares'] or 0),
            'cost_per_share': float(r['cost_per_share'] or 0),
            'fees':           float(r['fees'] or 0),
            'total_cost':     float(r['total_cost'] or 0),
            'created_at':     r['created_at'],
        })
        count += 1
    print(f"  Done ({count} rows)")

    # ── FHSA Deposits ─────────────────────────────────────────────────────────
    print("Migrating FHSA deposits...")
    cur.execute("SELECT * FROM fhsa_deposits")
    count = 0
    for row in cur.fetchall():
        r = dict(row)
        uid = uid_map.get(r['user_id'])
        if not uid:
            continue
        fs.collection('users').document(uid).collection('fhsa_deposits').add({
            'date':       r['date'],
            'amount':     float(r['amount'] or 0),
            'note':       r['note'] or '',
            'created_at': r['created_at'],
        })
        count += 1
    print(f"  Done ({count} rows)")

    # ── Net Worth Snapshots ───────────────────────────────────────────────────
    print("Migrating net worth snapshots...")
    cur.execute("SELECT * FROM networth_snapshots")
    count = 0
    for row in cur.fetchall():
        r = dict(row)
        uid = uid_map.get(r['user_id'])
        if not uid:
            continue
        fs.collection('users').document(uid).collection('networth_snapshots').document(r['month_key']).set({
            'month_key':  r['month_key'],
            'chequing':   float(r['chequing'] or 0),
            'cash':       float(r['cash'] or 0),
            'tfsa':       float(r['tfsa'] or 0),
            'total':      float(r['total'] or 0),
            'created_at': r['created_at'],
        })
        count += 1
    print(f"  Done ({count} rows)")

    # ── Goals ─────────────────────────────────────────────────────────────────
    print("Migrating goals...")
    cur.execute("SELECT * FROM goals")
    count = 0
    for row in cur.fetchall():
        r = dict(row)
        uid = uid_map.get(r['user_id'])
        if not uid:
            continue
        fs.collection('users').document(uid).collection('goals').add({
            'title':                  r['title'],
            'icon':                   r['icon'] or '',
            'color':                  r['color'] or '',
            'target_amount':          float(r['target_amount'] or 0),
            'current_amount':         float(r['current_amount'] or 0),
            'deadline':               r['deadline'],
            'monthly_contribution':   float(r['monthly_contribution'] or 0),
            'account':                r['account'] or '',
            'goal_type':              r['goal_type'] or '',
            'contribution_frequency': r['contribution_frequency'] or '',
            'streak_count':           int(r['streak_count'] or 0),
            'last_check_in':          r['last_check_in'],
            'created_at':             r['created_at'],
            'updated_at':             r['updated_at'],
        })
        count += 1
    print(f"  Done ({count} rows)")

    # ── Monthly Diaries ───────────────────────────────────────────────────────
    print("Migrating monthly diaries...")
    cur.execute("SELECT * FROM monthly_diaries")
    count = 0
    for row in cur.fetchall():
        r = dict(row)
        uid = uid_map.get(r['user_id'])
        if not uid:
            continue
        fs.collection('users').document(uid).collection('monthly_diaries').document(r['month_key']).set({
            'month_key':       r['month_key'],
            'overall_notes':   r['overall_notes'] or '',
            'next_month_focus': r['next_month_focus'] or '',
            'mood_rating':     r['mood_rating'],
            'created_at':      r['created_at'],
            'updated_at':      r['updated_at'],
        })
        count += 1
    print(f"  Done ({count} rows)")

    conn.close()
    print("\nMigration complete!")
    print(f"Migrated {len(uid_map)} users:")
    for old_id, new_uid in uid_map.items():
        print(f"  SQLite ID {old_id} → Firestore {new_uid}")

if __name__ == '__main__':
    migrate()

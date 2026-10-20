"""Auto-categorization and duplicate detection (US-11, US-12, US-08).

Pipeline, matching Sprint2.md section 4:
  1. normalize_merchant()      - "GROCERY STORE #123" -> "grocery store"
  2. merchant_rules lookup     - a per-user remembered override for that key
  3. KEYWORD_RULES             - simple substring rules
  4. LLM batch call            - whatever's still uncategorized, one fixed
                                  prompt, one JSON response for the whole batch
  5. default to Other / Other income, and never fail the upload if the AI
     call errors or no local Ollama server is available

detect_duplicates() implements US-08's match rule (same date, amount and
merchant_key as an existing *confirmed* transaction in the same account).
"""
import json
import re

import llm

DEFAULT_CATEGORIES = [
    # Income
    {'name': 'Salary', 'kind': 'income'},
    {'name': 'Freelance / Side income', 'kind': 'income'},
    {'name': 'Investment income', 'kind': 'income'},
    {'name': 'Refund', 'kind': 'income'},
    {'name': 'Other income', 'kind': 'income'},
    # Expense
    {'name': 'Groceries', 'kind': 'expense'},
    {'name': 'Dining', 'kind': 'expense'},
    {'name': 'Rent / Mortgage', 'kind': 'expense'},
    {'name': 'Utilities', 'kind': 'expense'},
    {'name': 'Transportation', 'kind': 'expense'},
    {'name': 'Shopping', 'kind': 'expense'},
    {'name': 'Entertainment', 'kind': 'expense'},
    {'name': 'Health', 'kind': 'expense'},
    {'name': 'Subscriptions', 'kind': 'expense'},
    {'name': 'Fees & interest', 'kind': 'expense'},
    {'name': 'Transfers', 'kind': 'expense'},
    {'name': 'Other', 'kind': 'expense'},
]

# Checked in order; first substring match wins. Keys are already lowercase
# merchant_key text (post normalize_merchant), so match on simple fragments.
KEYWORD_RULES = [
    # income
    ('payroll', 'Salary'), ('salary', 'Salary'), ('pay roll', 'Salary'),
    ('freelance', 'Freelance / Side income'), ('contract pay', 'Freelance / Side income'),
    ('dividend', 'Investment income'), ('interest earned', 'Investment income'), ('investment income', 'Investment income'),
    ('refund', 'Refund'), ('reversal', 'Refund'), ('chargeback', 'Refund'),
    # expense
    ('netflix', 'Subscriptions'), ('spotify', 'Subscriptions'), ('disney', 'Subscriptions'),
    ('hulu', 'Subscriptions'), ('prime video', 'Subscriptions'), ('subscription', 'Subscriptions'),
    ('icloud', 'Subscriptions'), ('youtube premium', 'Subscriptions'),
    ('grocery', 'Groceries'), ('groceries', 'Groceries'), ('supermarket', 'Groceries'), ('market', 'Groceries'), ('foods', 'Groceries'),
    ('restaurant', 'Dining'), ('cafe', 'Dining'), ('coffee', 'Dining'), ('diner', 'Dining'),
    ('pizza', 'Dining'), ('doordash', 'Dining'), ('uber eats', 'Dining'), ('takeout', 'Dining'), ('bakery', 'Dining'),
    ('rent payment', 'Rent / Mortgage'), ('rent', 'Rent / Mortgage'), ('mortgage', 'Rent / Mortgage'), ('landlord', 'Rent / Mortgage'),
    ('electric', 'Utilities'), ('hydro', 'Utilities'), ('water utility', 'Utilities'),
    ('gas utility', 'Utilities'), ('utility', 'Utilities'), ('internet', 'Utilities'), ('phone bill', 'Utilities'), ('cell phone', 'Utilities'),
    ('uber', 'Transportation'), ('lyft', 'Transportation'), ('transit', 'Transportation'),
    ('gas station', 'Transportation'), ('fuel', 'Transportation'), ('parking', 'Transportation'), ('car insurance', 'Transportation'),
    ('amazon', 'Shopping'), ('walmart', 'Shopping'), ('target', 'Shopping'), ('shopping', 'Shopping'), ('department store', 'Shopping'),
    ('movie', 'Entertainment'), ('cinema', 'Entertainment'), ('concert', 'Entertainment'), ('entertainment', 'Entertainment'), ('game', 'Entertainment'),
    ('pharmacy', 'Health'), ('clinic', 'Health'), ('doctor', 'Health'), ('dental', 'Health'), ('health', 'Health'), ('hospital', 'Health'), ('gym', 'Health'),
    ('late fee', 'Fees & interest'), ('overdraft', 'Fees & interest'), ('service charge', 'Fees & interest'),
    ('bank fee', 'Fees & interest'), ('interest charge', 'Fees & interest'),
    ('e transfer', 'Transfers'), ('etransfer', 'Transfers'), ('transfer to', 'Transfers'), ('transfer from', 'Transfers'),
]

_REFERENCE_NUM_RE = re.compile(r'#\s*\d+')
_LONG_DIGIT_RUN_RE = re.compile(r'\b\d{3,}\b')
_NON_ALPHA_RE = re.compile(r'[^a-z\s]')
_WHITESPACE_RE = re.compile(r'\s+')


def normalize_merchant(description):
    """'GROCERY STORE #123' -> 'grocery store'."""
    text = (description or '').lower()
    text = _REFERENCE_NUM_RE.sub('', text)
    text = _LONG_DIGIT_RUN_RE.sub('', text)
    text = _NON_ALPHA_RE.sub(' ', text)
    text = _WHITESPACE_RE.sub(' ', text).strip()
    return text


def keyword_category(merchant_key):
    for fragment, category_name in KEYWORD_RULES:
        if fragment in merchant_key:
            return category_name
    return None


# One-line definitions shown to the model; a small local model picks far more
# consistently with these than from bare category names.
CATEGORY_HINTS = {
    'Salary': 'regular pay from an employer (payroll, direct deposit from a company)',
    'Freelance / Side income': 'payouts from gig, marketplace or contract work',
    'Investment income': 'dividends, interest earned, brokerage distributions',
    'Refund': 'money returned for a purchase, tax refunds, reversals, rebates',
    'Other income': 'money in that fits nothing above',
    'Groceries': 'supermarkets, grocery chains, warehouse clubs, liquor/beer stores, food markets',
    'Dining': 'restaurants, cafes, coffee shops, fast food, bars, food delivery apps',
    'Rent / Mortgage': 'rent, mortgage payments, property management',
    'Utilities': 'electricity, gas/heating, water, internet, and ANY mobile/cell phone carrier or cable provider',
    'Transportation': 'fuel/gas stations, public transit, rideshare, trains, parking, car insurance and repairs',
    'Shopping': 'general retail, department stores, online stores, electronics, books, clothing, hardware',
    'Entertainment': 'one-off fun purchases: cinema and concert tickets, video games, events (NOT recurring streaming)',
    'Health': 'pharmacies, doctors, dentists, clinics, hospitals, gyms and fitness',
    'Subscriptions': 'recurring digital services: any streaming video/music service, cloud storage, software plans',
    'Fees & interest': 'bank fees, account or card fees, NSF/overdraft, late fees, interest charged',
    'Transfers': 'moving money between accounts or people: e-transfers, transfers to savings, credit card payments',
    'Other': 'money out that fits nothing above, or where the merchant is unrecognizable',
}

# Worked examples for the prompt, kept separate from the test/eval merchants.
CATEGORY_EXAMPLES = {
    'money out': [
        ('VIRGIN PLUS WIRELESS', 'mobile phone carrier', 'Utilities'),
        ('HBO MAX', 'video streaming service', 'Subscriptions'),
        ('FRESHCO #882', 'grocery chain', 'Groceries'),
        ('ESSO 4410', 'gas station', 'Transportation'),
        ('A&W #1192', 'fast food restaurant', 'Dining'),
        ('HOME DEPOT 7051', 'hardware retailer', 'Shopping'),
        ('SQ *BLUEWATER LLC', 'unrecognizable merchant', 'Other'),
    ],
    'money in': [
        ('DIRECT DEPOSIT GLOBEX LTD', 'employer payroll', 'Salary'),
        ('FIVERR PAYOUT', 'gig marketplace payout', 'Freelance / Side income'),
        ('ONLINE BANKING PAYMENT RECEIVED', 'credit card payment', 'Transfers'),
    ],
}

# Small models lose track of indexes in long lists, so categorize in chunks.
LLM_BATCH_SIZE = 15

CATEGORIZE_PROMPT = """You categorize bank transactions for a personal finance app.

For each transaction, first identify what kind of business or payment the
description refers to (use your knowledge of brand names; descriptions are
often abbreviated and may contain store numbers), then pick the single best
category from the list. Use "{fallback}" only if the merchant is genuinely
unrecognizable - do not guess a category from vague words like "store" or
"purchase".

Categories:
{categories}

Examples (business type -> category):
{examples}

Transactions ({direction}):
{lines}

Return one entry per transaction, in the same order, copying its index and
description exactly."""


def _categorize_schema(category_names):
    # The enum constrains the local model to valid category names.
    return {
        'type': 'object',
        'properties': {
            'categories': {
                'type': 'array',
                'items': {
                    'type': 'object',
                    'properties': {
                        'index': {'type': 'integer'},
                        'description': {'type': 'string'},
                        'business_type': {'type': 'string'},
                        'category': {'type': 'string', 'enum': category_names},
                    },
                    'required': ['index', 'description', 'business_type', 'category'],
                },
            },
        },
        'required': ['categories'],
    }


def _llm_categorize_batch(batch, category_names, fallback, direction):
    lines = '\n'.join(f'{i}. {tx["description"]} (${tx["amount"]:.2f})' for i, tx in enumerate(batch))
    categories = '\n'.join(f'- {name}: {CATEGORY_HINTS[name]}' if name in CATEGORY_HINTS else f'- {name}'
                            for name in category_names)
    examples = '\n'.join(f'- {desc} -> {kind} -> {name}' for desc, kind, name in CATEGORY_EXAMPLES[direction]
                         if name in category_names)
    prompt = CATEGORIZE_PROMPT.format(fallback=fallback, categories=categories, examples=examples,
                                      direction=direction, lines=lines)
    result = llm.structured_chat(prompt, _categorize_schema(category_names))
    for row in result.get('categories', []):
        idx = row.get('index')
        if isinstance(idx, int) and 0 <= idx < len(batch) and row.get('category') in category_names:
            batch[idx]['category'] = row['category']


def _llm_categorize(uncertain, categories_by_name):
    """Mutates each tx in `uncertain` with a 'category' name key, best-effort.
    Never raises - a failed/unavailable AI call just leaves items uncategorized
    so the caller's default ("Other"/"Other income") applies instead.

    Credits and debits are sent separately, each limited to categories of the
    matching kind (plus Transfers, which goes both ways)."""
    def names_for(kind):
        return [n for n, c in categories_by_name.items() if c.get('kind') == kind or n == 'Transfers']

    groups = [
        ([tx for tx in uncertain if tx.get('type') == 'credit'], names_for('income'),
         'Other income', 'money in'),
        ([tx for tx in uncertain if tx.get('type') != 'credit'], names_for('expense'),
         'Other', 'money out'),
    ]
    for txs, names, fallback, direction in groups:
        for i in range(0, len(txs), LLM_BATCH_SIZE):
            try:
                _llm_categorize_batch(txs[i:i + LLM_BATCH_SIZE], names, fallback, direction)
            except Exception:
                return  # fall through to the default category - never block saving


def categorize_transactions(transactions, categories_by_name, merchant_rules):
    """Mutates each tx in `transactions` with 'merchant_key' and 'category_id'.
    merchant_rules: {merchant_key: category_id} for this user."""
    uncertain = []
    for tx in transactions:
        key = normalize_merchant(tx.get('description'))
        tx['merchant_key'] = key

        if key in merchant_rules:
            tx['category_id'] = merchant_rules[key]
            continue

        name = keyword_category(key)
        if name and name in categories_by_name:
            tx['category_id'] = categories_by_name[name]['_id']
            continue

        uncertain.append(tx)

    if uncertain:
        _llm_categorize(uncertain, categories_by_name)

    for tx in uncertain:
        if tx.get('category_id'):
            continue
        name = tx.get('category')
        if name and name in categories_by_name:
            tx['category_id'] = categories_by_name[name]['_id']
        else:
            default_name = 'Other income' if tx.get('type') == 'credit' else 'Other'
            tx['category_id'] = categories_by_name[default_name]['_id']
        tx.pop('category', None)

    return transactions


def detect_duplicates(new_transactions, existing_transactions):
    """US-08 match rule: same date, amount and merchant_key as an existing
    (already-confirmed) transaction in the same account. Mutates each new tx
    with 'is_duplicate'."""
    existing_keys = {
        (t.get('date'), round(float(t.get('amount') or 0), 2), t.get('merchant_key'))
        for t in existing_transactions
    }
    for tx in new_transactions:
        key = (tx.get('date'), round(float(tx.get('amount') or 0), 2), tx.get('merchant_key'))
        tx['is_duplicate'] = key in existing_keys
    return new_transactions

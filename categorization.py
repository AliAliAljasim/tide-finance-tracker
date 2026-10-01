"""Auto-categorization and duplicate detection (US-11, US-12, US-08).

Pipeline, matching Sprint2.md section 4:
  1. normalize_merchant()      - "GROCERY STORE #123" -> "grocery store"
  2. merchant_rules lookup     - a per-user remembered override for that key
  3. KEYWORD_RULES             - simple substring rules
  4. LLM batch call            - whatever's still uncategorized, one fixed
                                  prompt, one JSON response for the whole batch
  5. default to Other / Other income, and never fail the upload if the AI
     call errors or no API key is configured

detect_duplicates() implements US-08's match rule (same date, amount and
merchant_key as an existing *confirmed* transaction in the same account).
"""
import json
import os
import re

try:
    import anthropic
except ImportError:
    anthropic = None

ANTHROPIC_MODEL = os.environ.get('ANTHROPIC_MODEL', 'claude-sonnet-5')

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


CATEGORIZE_SCHEMA = {
    'name': 'categorize_transactions',
    'description': 'Assign one category to each transaction, by index.',
    'input_schema': {
        'type': 'object',
        'properties': {
            'categories': {
                'type': 'array',
                'items': {
                    'type': 'object',
                    'properties': {
                        'index': {'type': 'integer'},
                        'category': {'type': 'string'},
                    },
                    'required': ['index', 'category'],
                },
            },
        },
        'required': ['categories'],
    },
}


def _llm_categorize(uncertain, category_names):
    """Mutates each tx in `uncertain` with a 'category' name key, best-effort.
    Never raises - a failed/unavailable AI call just leaves items uncategorized
    so the caller's default ("Other"/"Other income") applies instead."""
    api_key = os.environ.get('ANTHROPIC_API_KEY')
    if not api_key or anthropic is None or not uncertain:
        return
    try:
        client = anthropic.Anthropic(api_key=api_key)
        lines = '\n'.join(f'{i}. {tx["description"]} ({tx["type"]}, ${tx["amount"]:.2f})'
                           for i, tx in enumerate(uncertain))
        prompt = (
            'Assign exactly one of these categories to each transaction below, '
            'by its index. Categories: ' + ', '.join(category_names) + '.\n\n' + lines
        )
        response = client.messages.create(
            model=ANTHROPIC_MODEL, max_tokens=2048,
            tools=[CATEGORIZE_SCHEMA],
            tool_choice={'type': 'tool', 'name': 'categorize_transactions'},
            messages=[{'role': 'user', 'content': prompt}],
        )
        for block in response.content:
            if block.type == 'tool_use':
                for row in block.input.get('categories', []):
                    idx = row.get('index')
                    if idx is not None and 0 <= idx < len(uncertain) and row.get('category') in category_names:
                        uncertain[idx]['category'] = row['category']
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
        _llm_categorize(uncertain, list(categories_by_name.keys()))

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

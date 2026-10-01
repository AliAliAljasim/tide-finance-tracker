"""Unit tests for categorization.py (US-11, US-12, US-08).

Covers Sprint2.md's testing list: normalizeMerchant() on sample
descriptions, merchant rule overrides keyword and AI categories, and the
duplicate match rule (match / no-match cases).
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from categorization import (
    DEFAULT_CATEGORIES, normalize_merchant, keyword_category,
    categorize_transactions, detect_duplicates,
)

# Fake categories keyed by name -> {'_id': name}, good enough for these tests
# since categorize_transactions only ever does categories_by_name[name]['_id'].
CATEGORIES = {c['name']: {'_id': c['name'], 'kind': c['kind']} for c in DEFAULT_CATEGORIES}


def test_normalize_merchant_strips_store_number():
    assert normalize_merchant('GROCERY STORE #123') == 'grocery store'


def test_normalize_merchant_strips_long_digit_runs():
    assert normalize_merchant('AMAZON.COM*AB12345XYZ') == 'amazon com ab xyz'


def test_normalize_merchant_lowercases_and_collapses_whitespace():
    assert normalize_merchant('  Netflix.com   ') == 'netflix com'


def test_normalize_merchant_handles_empty():
    assert normalize_merchant('') == ''
    assert normalize_merchant(None) == ''


def test_keyword_category_common_merchants():
    cases = {
        'payroll deposit': 'Salary',
        'netflix com': 'Subscriptions',
        'grocery mart': 'Groceries',
        'uber trip': 'Transportation',
        'rent payment': 'Rent / Mortgage',
        'refund': 'Refund',
        'electric utility bill': 'Utilities',
        'pharmacy': 'Health',
    }
    for key, expected in cases.items():
        assert keyword_category(key) == expected, key


def test_keyword_category_no_match_returns_none():
    assert keyword_category('xyzzy unknown merchant') is None


def test_categorize_transactions_applies_keyword_rule():
    txs = [{'description': 'NETFLIX.COM', 'type': 'debit', 'amount': 15.99}]
    categorize_transactions(txs, CATEGORIES, merchant_rules={})
    assert txs[0]['category_id'] == 'Subscriptions'
    assert txs[0]['merchant_key'] == 'netflix com'


def test_categorize_transactions_merchant_rule_overrides_keyword():
    # "netflix com" would normally hit the Subscriptions keyword rule, but the
    # user previously re-categorized this merchant as Entertainment.
    txs = [{'description': 'NETFLIX.COM', 'type': 'debit', 'amount': 15.99}]
    rules = {'netflix com': 'Entertainment'}
    categorize_transactions(txs, CATEGORIES, merchant_rules=rules)
    assert txs[0]['category_id'] == 'Entertainment'


def test_categorize_transactions_defaults_to_other_when_unmatched():
    # No ANTHROPIC_API_KEY in the test environment, so this exercises the
    # final fallback rather than a real AI call.
    os.environ.pop('ANTHROPIC_API_KEY', None)
    debit = {'description': 'XYZZY UNKNOWN MERCHANT', 'type': 'debit', 'amount': 10}
    credit = {'description': 'XYZZY UNKNOWN MERCHANT', 'type': 'credit', 'amount': 10}
    categorize_transactions([debit, credit], CATEGORIES, merchant_rules={})
    assert debit['category_id'] == 'Other'
    assert credit['category_id'] == 'Other income'


def test_detect_duplicates_matches_same_date_amount_merchant():
    existing = [{'date': '2026-08-03', 'amount': 54.20, 'merchant_key': 'grocery store'}]
    new = [{'date': '2026-08-03', 'amount': 54.20, 'merchant_key': 'grocery store'}]
    detect_duplicates(new, existing)
    assert new[0]['is_duplicate'] is True


def test_detect_duplicates_no_match_when_amount_differs():
    existing = [{'date': '2026-08-03', 'amount': 54.20, 'merchant_key': 'grocery store'}]
    new = [{'date': '2026-08-03', 'amount': 60.00, 'merchant_key': 'grocery store'}]
    detect_duplicates(new, existing)
    assert new[0]['is_duplicate'] is False


def test_detect_duplicates_no_match_when_date_differs():
    existing = [{'date': '2026-08-03', 'amount': 54.20, 'merchant_key': 'grocery store'}]
    new = [{'date': '2026-08-10', 'amount': 54.20, 'merchant_key': 'grocery store'}]
    detect_duplicates(new, existing)
    assert new[0]['is_duplicate'] is False


def test_detect_duplicates_no_match_when_merchant_differs():
    existing = [{'date': '2026-08-03', 'amount': 54.20, 'merchant_key': 'grocery store'}]
    new = [{'date': '2026-08-03', 'amount': 54.20, 'merchant_key': 'coffee shop'}]
    detect_duplicates(new, existing)
    assert new[0]['is_duplicate'] is False

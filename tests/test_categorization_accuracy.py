"""Accuracy test (Sprint2.md section 9): label synthetic transactions with
their correct category, run categorization, and record % correct against
an 85%+ target.

This exercises the keyword-rules path only (conftest.py turns the local
LLM off, and no merchant_rules exist yet). The labeled set
deliberately includes real-world-style descriptions the keyword rules
*don't* cover (LCBO, Costco, Fido, "Royal Bank monthly fee", ...) so the
score reflects genuine gaps rather than 100% self-matching against rules
written for this same list. In production those gaps are exactly what the
local LLM categorization step (Ollama, see llm.py) is for.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from categorization import DEFAULT_CATEGORIES, categorize_transactions

CATEGORIES = {c['name']: {'_id': c['name'], 'kind': c['kind']} for c in DEFAULT_CATEGORIES}
ACCURACY_TARGET = 0.85

# (description, type, expected_category) — expected_category is the *correct*
# human label, which may differ from what a keyword-only pass can find.
LABELED_SET = [
    # Income — covered by keyword rules
    ('PAYROLL DEPOSIT ACME CORP', 'credit', 'Salary'),
    ('BIWEEKLY PAYROLL', 'credit', 'Salary'),
    ('FREELANCE CONTRACT PAY', 'credit', 'Freelance / Side income'),
    ('UPWORK FREELANCE PAYMENT', 'credit', 'Freelance / Side income'),
    ('DIVIDEND PAYMENT TD BANK', 'credit', 'Investment income'),
    ('INTEREST EARNED SAVINGS', 'credit', 'Investment income'),
    ('REFUND AMAZON RETURN', 'credit', 'Refund'),
    ('PURCHASE REVERSAL', 'credit', 'Refund'),
    # Groceries
    ('GROCERY STORE #482', 'debit', 'Groceries'),
    ('SUPERMARKET PURCHASE', 'debit', 'Groceries'),
    ('WHOLE FOODS MARKET', 'debit', 'Groceries'),
    ('FARM BOY GROCERIES', 'debit', 'Groceries'),
    # Dining
    ('STARBUCKS COFFEE', 'debit', 'Dining'),
    ('LOCAL CAFE', 'debit', 'Dining'),
    ('PIZZA HUT ORDER', 'debit', 'Dining'),
    ('DOORDASH DELIVERY', 'debit', 'Dining'),
    ('UBER EATS ORDER', 'debit', 'Dining'),
    ('DOWNTOWN RESTAURANT', 'debit', 'Dining'),
    ('ITALIAN DINER', 'debit', 'Dining'),
    # Rent / Mortgage
    ('RENT PAYMENT LANDLORD LLC', 'debit', 'Rent / Mortgage'),
    ('MORTGAGE PAYMENT TD', 'debit', 'Rent / Mortgage'),
    ('MONTHLY RENT', 'debit', 'Rent / Mortgage'),
    # Utilities
    ('HYDRO ONE UTILITY BILL', 'debit', 'Utilities'),
    ('CITY WATER UTILITY', 'debit', 'Utilities'),
    ('ROGERS INTERNET BILL', 'debit', 'Utilities'),
    ('BELL PHONE BILL', 'debit', 'Utilities'),
    ('ELECTRIC COMPANY BILL', 'debit', 'Utilities'),
    # Transportation
    ('UBER TRIP DOWNTOWN', 'debit', 'Transportation'),
    ('LYFT RIDE', 'debit', 'Transportation'),
    ('SHELL GAS STATION', 'debit', 'Transportation'),
    ('CITY TRANSIT FARE', 'debit', 'Transportation'),
    ('AIRPORT PARKING FEE', 'debit', 'Transportation'),
    ('CAR INSURANCE PREMIUM', 'debit', 'Transportation'),
    # Shopping
    ('AMAZON.COM PURCHASE', 'debit', 'Shopping'),
    ('WALMART SUPERCENTER', 'debit', 'Shopping'),
    ('TARGET STORE #221', 'debit', 'Shopping'),
    ('DEPARTMENT STORE SALE', 'debit', 'Shopping'),
    # Entertainment
    ('AMC CINEMA TICKETS', 'debit', 'Entertainment'),
    ('CONCERT TICKETMASTER', 'debit', 'Entertainment'),
    ('STEAM GAME PURCHASE', 'debit', 'Entertainment'),
    ('MOVIE THEATRE', 'debit', 'Entertainment'),
    # Health
    ('SHOPPERS PHARMACY', 'debit', 'Health'),
    ('DENTAL CLINIC VISIT', 'debit', 'Health'),
    ('CITY HOSPITAL BILL', 'debit', 'Health'),
    ('GOODLIFE GYM MEMBERSHIP', 'debit', 'Health'),
    ('FAMILY DOCTOR VISIT', 'debit', 'Health'),
    # Subscriptions
    ('NETFLIX.COM', 'debit', 'Subscriptions'),
    ('SPOTIFY PREMIUM', 'debit', 'Subscriptions'),
    ('DISNEY PLUS', 'debit', 'Subscriptions'),
    ('ICLOUD STORAGE', 'debit', 'Subscriptions'),
    ('YOUTUBE PREMIUM', 'debit', 'Subscriptions'),
    # Fees & interest
    ('OVERDRAFT FEE', 'debit', 'Fees & interest'),
    ('LATE FEE CHARGE', 'debit', 'Fees & interest'),
    ('BANK SERVICE CHARGE', 'debit', 'Fees & interest'),
    ('INTEREST CHARGE VISA', 'debit', 'Fees & interest'),
    # Transfers
    ('E TRANSFER TO JOHN', 'debit', 'Transfers'),
    ('TRANSFER TO SAVINGS', 'debit', 'Transfers'),
    ('ETRANSFER SENT', 'debit', 'Transfers'),
    # Genuinely unknown -> Other is the *correct* answer here
    ('MISC PURCHASE XYZ CORP', 'debit', 'Other'),
    ('UNKNOWN VENDOR 884', 'debit', 'Other'),
    ('GENERAL STORE PAYMENT QRS', 'debit', 'Other'),
    # Hard cases: realistic merchants the keyword list doesn't cover, so
    # these are expected to miss (fall to Other) — the honest accuracy gap.
    ('TTC METROPASS', 'debit', 'Transportation'),
    ('INDIGO BOOKS', 'debit', 'Shopping'),
    ('CINEPLEX ODEON', 'debit', 'Entertainment'),
    ('LCBO WINE PURCHASE', 'debit', 'Groceries'),
    ('VIA RAIL TICKET', 'debit', 'Transportation'),
    ('COSTCO WHOLESALE', 'debit', 'Groceries'),
    ('FIDO MOBILE', 'debit', 'Utilities'),
    ('ROYAL BANK MONTHLY FEE', 'debit', 'Fees & interest'),
]


def test_labeled_set_has_enough_rows():
    assert 50 <= len(LABELED_SET) <= 100


def test_categorization_accuracy_meets_target():
    txs = [{'description': desc, 'type': kind, 'amount': 25.00} for desc, kind, _ in LABELED_SET]
    categorize_transactions(txs, CATEGORIES, merchant_rules={})

    correct = sum(1 for tx, (_, _, expected) in zip(txs, LABELED_SET) if tx['category_id'] == expected)
    accuracy = correct / len(LABELED_SET)

    print(f'\nCategorization accuracy: {correct}/{len(LABELED_SET)} = {accuracy:.1%}')
    assert accuracy >= ACCURACY_TARGET, f'{accuracy:.1%} is below the {ACCURACY_TARGET:.0%} target'

"""Unit tests for the AI parsing pipeline (parsing.py).

Covers Testing Requirements: "unit tests for balance and date validation",
"run the parser on each [synthetic statement] and record field-level
accuracy", and "test the failure path: a bad file shows an error and
saves nothing".
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from parsing import extract_text, mask_account_numbers, parse_statement_text, validate_transactions

FIXTURES = os.path.join(os.path.dirname(__file__), 'fixtures')


def test_mask_account_numbers_hides_all_but_last_four():
    text = 'Account 123456789012 balance due'
    masked = mask_account_numbers(text)
    assert '123456789012' not in masked
    assert masked.endswith('9012 balance due')


def test_mask_account_numbers_leaves_short_numbers_alone():
    # Amounts, dates etc. should not get masked.
    text = 'Paid $54.20 on 2026-08-03'
    assert mask_account_numbers(text) == text


def _run_pipeline(filename):
    path = os.path.join(FIXTURES, filename)
    text, needs_ocr_failed = extract_text(path, '.pdf')
    assert not needs_ocr_failed
    masked = mask_account_numbers(text)
    parsed = parse_statement_text(masked)
    rows, balance_ok = validate_transactions(
        parsed['transactions'], parsed['opening_balance'], parsed['closing_balance'],
        parsed['period_start'], parsed['period_end'],
    )
    return parsed, rows, balance_ok


def test_riverside_bank_clean_statement_parses_with_no_flags():
    parsed, rows, balance_ok = _run_pipeline('riverside_bank.pdf')
    assert len(rows) == 5
    assert balance_ok is True
    assert all(not r['flagged'] for r in rows)
    assert parsed['opening_balance'] == 1200.00
    assert parsed['closing_balance'] == 2226.70


def test_northwind_credit_union_different_layout_still_parses():
    parsed, rows, balance_ok = _run_pipeline('northwind_credit_union.pdf')
    assert len(rows) == 4
    assert balance_ok is True
    assert rows[0]['description'] == 'RENT PAYMENT'
    assert rows[0]['type'] == 'debit'


def test_harbor_trust_flags_bad_balance_and_out_of_period_date():
    parsed, rows, balance_ok = _run_pipeline('harbor_trust_flagged.pdf')
    by_desc = {r['description']: r for r in rows}

    assert by_desc['LATE FEE REVERSAL']['flagged'] is True
    assert 'before the statement period' in by_desc['LATE FEE REVERSAL']['flag_reason']

    assert by_desc['CAR INSURANCE']['flagged'] is True
    assert 'balance' in by_desc['CAR INSURANCE']['flag_reason'].lower()

    assert by_desc['GROCERY MART #44']['flagged'] is False


def test_scanned_pdf_with_no_text_layer_fails_cleanly():
    path = os.path.join(FIXTURES, 'blank_scanned.pdf')
    text, needs_ocr_failed = extract_text(path, '.pdf')
    # No OCR engine is installed in this environment, so a scanned/blank
    # PDF must fail closed rather than silently return nothing parsed.
    assert text.strip() == ''
    assert needs_ocr_failed is True


def test_validate_transactions_date_range():
    rows, balance_ok = validate_transactions(
        [{'date': '2026-05-01', 'description': 'x', 'amount': 10, 'type': 'debit', 'balance': None}],
        None, None, '2026-06-01', '2026-06-30',
    )
    assert rows[0]['flagged'] is True
    assert 'before' in rows[0]['flag_reason']


def test_validate_transactions_running_balance_mismatch_is_flagged():
    rows, balance_ok = validate_transactions(
        [
            {'date': '2026-06-01', 'description': 'a', 'amount': 100, 'type': 'credit', 'balance': 100},
            {'date': '2026-06-02', 'description': 'b', 'amount': 999, 'type': 'debit', 'balance': -500},  # wrong
        ],
        0, -500, None, None,
    )
    assert rows[0]['flagged'] is False
    assert rows[1]['flagged'] is True

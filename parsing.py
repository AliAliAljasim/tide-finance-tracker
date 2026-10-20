"""AI statement-parsing pipeline (US-05, US-06).

Steps, matching Week3_Sprint1_Requirements.md section 3:
  1. extract_text()            - read the PDF's text layer
  2. extract_text()            - OCR scanned PDFs / images (best-effort; see note below)
  3. mask_account_numbers()    - mask account numbers before anything leaves the app
  4. parse_statement_text()    - send the (masked) text to an LLM with a fixed
                                  prompt + JSON schema, one record per transaction
  5. validate_transactions()   - opening + transactions == closing, dates inside
                                  the statement period, flag rows that fail

OCR note: this environment has no tesseract binary installed, so OCR is wired
up to call pytesseract if it's available and fails closed (clear error,
nothing saved) if it isn't, rather than silently skipping it. In production
pytesseract + the tesseract-ocr system package (or a hosted OCR API) would be
installed alongside the app.

AI note: transactions are extracted by a local LLM served by Ollama (see
llm.py), constrained to a fixed JSON schema. When no Ollama server is
configured or reachable, a small deterministic parser stands in so the
upload -> review -> confirm flow can still be demoed end-to-end; it is NOT
the AI pipeline and is clearly separated below.
"""
import json
import re
from datetime import datetime

try:
    import pdfplumber
except ImportError:
    pdfplumber = None

try:
    from PIL import Image
except ImportError:
    Image = None

try:
    import pytesseract
except ImportError:
    pytesseract = None

import llm

# Matches long digit runs (8+, with optional spaces/dashes) that look like
# account or card numbers, e.g. "1234 5678 9012" or "123456789012".
_ACCOUNT_NUMBER_RE = re.compile(r'\b(?:\d[ -]?){8,}\d\b')


def mask_account_numbers(text):
    def _mask(match):
        digits = re.sub(r'[ -]', '', match.group(0))
        return 'X' * (len(digits) - 4) + digits[-4:]
    return _ACCOUNT_NUMBER_RE.sub(_mask, text)


def extract_text(file_path, ext):
    """Returns (text, needs_ocr_failed). needs_ocr_failed is True only when
    OCR was required but unavailable/failed, so the caller can show a more
    specific error than "couldn't read this file"."""
    if ext == '.pdf':
        text = _extract_pdf_text(file_path)
        if text.strip():
            return text, False
        # No text layer -> this is a scanned PDF; fall through to OCR.
        return _ocr_pdf(file_path)
    return _ocr_image(file_path)


def _extract_pdf_text(file_path):
    if pdfplumber is None:
        return ''
    text_parts = []
    with pdfplumber.open(file_path) as pdf:
        for page in pdf.pages:
            text_parts.append(page.extract_text() or '')
    return '\n'.join(text_parts)


def _ocr_image(file_path):
    if pytesseract is None or Image is None:
        return '', True
    try:
        with Image.open(file_path) as img:
            return pytesseract.image_to_string(img), False
    except Exception:
        return '', True


def _ocr_pdf(file_path):
    if pytesseract is None or Image is None or pdfplumber is None:
        return '', True
    try:
        text_parts = []
        with pdfplumber.open(file_path) as pdf:
            for page in pdf.pages:
                img = page.to_image(resolution=200).original
                text_parts.append(pytesseract.image_to_string(img))
        return '\n'.join(text_parts), False
    except Exception:
        return '', True


TRANSACTION_SCHEMA = {
    'type': 'object',
    'properties': {
        'period_start': {'type': ['string', 'null'], 'description': 'Statement period start, YYYY-MM-DD'},
        'period_end': {'type': ['string', 'null'], 'description': 'Statement period end, YYYY-MM-DD'},
        'opening_balance': {'type': ['number', 'null']},
        'closing_balance': {'type': ['number', 'null']},
        'transactions': {
            'type': 'array',
            'items': {
                'type': 'object',
                'properties': {
                    'date': {'type': 'string', 'description': 'YYYY-MM-DD'},
                    'description': {'type': 'string'},
                    'amount': {'type': 'number', 'description': 'Always positive'},
                    'type': {'type': 'string', 'enum': ['debit', 'credit']},
                    'balance': {'type': ['number', 'null'], 'description': 'Running balance if printed on the statement'},
                },
                'required': ['date', 'description', 'amount', 'type'],
            },
        },
    },
    'required': ['transactions'],
}

FIXED_PROMPT = (
    "You are extracting transactions from a bank statement's text. Account "
    "numbers have already been masked. Reply with JSON listing every "
    "transaction you find, one record per transaction, plus the statement's "
    "period and opening/closing balance if they are printed on the "
    "statement. Amounts are always positive; use type to say debit (money "
    "out, usually printed with a minus sign) or credit (money in). Do not "
    "invent transactions that are not in the text."
)


class ParsingError(Exception):
    pass


def parse_statement_text(masked_text):
    """Returns {period_start, period_end, opening_balance, closing_balance, transactions}."""
    if not masked_text.strip():
        # Never hand the model an empty prompt - it will invent transactions.
        raise ParsingError('Could not read any text from this statement.')
    try:
        parsed = llm.structured_chat(FIXED_PROMPT + '\n\nStatement text:\n' + masked_text,
                                     TRANSACTION_SCHEMA)
    except llm.LLMUnavailable:
        return _parse_with_fallback(masked_text)
    except llm.LLMError as e:
        raise ParsingError(f'The AI parsing service failed: {e}')
    if not isinstance(parsed, dict) or not isinstance(parsed.get('transactions'), list):
        raise ParsingError('The AI service did not return any transactions.')
    _normalize_amounts(parsed)
    return parsed


def _normalize_amounts(parsed):
    """Small local models often get the sign/type backwards, so derive them
    from the numbers instead: amounts are made positive, and debit vs credit
    comes from the running balance moving down/up (or the sign if no balance
    is printed)."""
    prev_balance = parsed.get('opening_balance')
    for tx in parsed['transactions']:
        try:
            amount = float(tx.get('amount'))
        except (TypeError, ValueError):
            continue
        balance = tx.get('balance')
        if isinstance(balance, (int, float)) and isinstance(prev_balance, (int, float)) and balance != prev_balance:
            tx['type'] = 'credit' if balance > prev_balance else 'debit'
        elif amount < 0:
            tx['type'] = 'debit'
        tx['amount'] = abs(amount)
        if isinstance(balance, (int, float)):
            prev_balance = balance


# ── Fallback parser (used only when no Ollama server is available) ──
#
# Expects lines like:
#   Period: 2026-08-01 to 2026-08-31
#   Opening Balance: 1200.00
#   2026-08-03 | GROCERY STORE #123 | -$54.20 | $1145.80
#   2026-08-05 | PAYROLL DEPOSIT | $1500.00 | $2645.80
#   Closing Balance: 2645.80
# This mirrors the synthetic test statements in tests/fixtures/.

_PERIOD_RE = re.compile(r'period[:\s]+(\d{4}-\d{2}-\d{2})\s*(?:to|-|–)\s*(\d{4}-\d{2}-\d{2})', re.I)
_OPENING_RE = re.compile(r'opening balance[:\s]+\$?(-?[\d,]+\.\d{2})', re.I)
_CLOSING_RE = re.compile(r'closing balance[:\s]+\$?(-?[\d,]+\.\d{2})', re.I)
_TX_LINE_RE = re.compile(
    r'^(\d{4}-\d{2}-\d{2})\s*\|\s*(.+?)\s*\|\s*(-?\$?[\d,]+\.\d{2})\s*\|\s*\$?(-?[\d,]+\.\d{2})\s*$'
)


def _to_float(s):
    return float(s.replace(',', '').replace('$', ''))


def _parse_with_fallback(masked_text):
    period_match = _PERIOD_RE.search(masked_text)
    opening_match = _OPENING_RE.search(masked_text)
    closing_match = _CLOSING_RE.search(masked_text)

    transactions = []
    for line in masked_text.splitlines():
        m = _TX_LINE_RE.match(line.strip('\n'))
        if not m:
            continue
        date_str, description, amount_str, balance_str = m.groups()
        amount = _to_float(amount_str)
        transactions.append({
            'date': date_str,
            'description': description.strip(),
            'amount': abs(amount),
            'type': 'credit' if amount >= 0 else 'debit',
            'balance': _to_float(balance_str),
        })

    return {
        'period_start': period_match.group(1) if period_match else None,
        'period_end': period_match.group(2) if period_match else None,
        'opening_balance': _to_float(opening_match.group(1)) if opening_match else None,
        'closing_balance': _to_float(closing_match.group(1)) if closing_match else None,
        'transactions': transactions,
    }


# ── Validation (spec step 6) ──────────────────────────────────────────────

def validate_transactions(transactions, opening_balance, closing_balance, period_start, period_end):
    """Flags rows that fail balance or date-range checks. Returns (rows, balance_ok)."""
    # Balance math follows the statement's own posting order (transactions
    # aren't necessarily in calendar-date order, e.g. a backdated reversal);
    # callers that want date order for display sort separately.
    rows = [dict(t) for t in transactions]

    running = float(opening_balance) if opening_balance is not None else None
    for tx in rows:
        flags = []

        if period_start and tx.get('date') and tx['date'] < period_start:
            flags.append('Date is before the statement period.')
        if period_end and tx.get('date') and tx['date'] > period_end:
            flags.append('Date is after the statement period.')

        amount = float(tx.get('amount') or 0)
        signed = amount if tx.get('type') == 'credit' else -amount
        if running is not None:
            expected = round(running + signed, 2)
            stated = tx.get('balance')
            if stated is not None and abs(round(float(stated), 2) - expected) > 0.01:
                flags.append('Running balance does not match the statement.')
                running = round(float(stated), 2)  # trust the statement for the next row
            else:
                running = round(float(stated), 2) if stated is not None else expected
        tx['flagged'] = bool(flags)
        tx['flag_reason'] = ' '.join(flags)

    balance_ok = True
    if opening_balance is not None and closing_balance is not None and running is not None:
        balance_ok = abs(round(running, 2) - round(float(closing_balance), 2)) <= 0.01

    return rows, balance_ok

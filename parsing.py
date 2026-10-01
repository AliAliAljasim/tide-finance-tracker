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

AI note: when ANTHROPIC_API_KEY is set, transactions are extracted by calling
the Anthropic API with a fixed tool-use JSON schema. Without a key configured
(e.g. running this scaffold locally without credentials), a small deterministic
parser stands in so the upload -> review -> confirm flow can still be demoed
end-to-end; it is NOT the AI pipeline and is clearly separated below.
"""
import json
import os
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

try:
    import anthropic
except ImportError:
    anthropic = None

ANTHROPIC_MODEL = os.environ.get('ANTHROPIC_MODEL', 'claude-sonnet-5')

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
    'name': 'record_transactions',
    'description': 'Record every transaction found in a bank statement.',
    'input_schema': {
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
    },
}

FIXED_PROMPT = (
    "You are extracting transactions from a bank statement's text. Account "
    "numbers have already been masked. Call record_transactions with every "
    "transaction you find, one record per transaction, plus the statement's "
    "period and opening/closing balance if they are printed on the "
    "statement. Amounts are always positive; use type to say debit or "
    "credit. Do not invent transactions that are not in the text."
)


class ParsingError(Exception):
    pass


def parse_statement_text(masked_text):
    """Returns {period_start, period_end, opening_balance, closing_balance, transactions}."""
    api_key = os.environ.get('ANTHROPIC_API_KEY')
    if api_key and anthropic is not None:
        return _parse_with_llm(masked_text, api_key)
    return _parse_with_fallback(masked_text)


def _parse_with_llm(masked_text, api_key):
    client = anthropic.Anthropic(api_key=api_key)
    try:
        response = client.messages.create(
            model=ANTHROPIC_MODEL,
            max_tokens=4096,
            tools=[TRANSACTION_SCHEMA],
            tool_choice={'type': 'tool', 'name': 'record_transactions'},
            messages=[{'role': 'user', 'content': FIXED_PROMPT + '\n\nStatement text:\n' + masked_text}],
        )
    except Exception as e:
        raise ParsingError(f'The AI parsing service failed: {e}')

    for block in response.content:
        if block.type == 'tool_use':
            return block.input
    raise ParsingError('The AI service did not return any transactions.')


# ── Fallback parser (used only when ANTHROPIC_API_KEY is not configured) ──
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

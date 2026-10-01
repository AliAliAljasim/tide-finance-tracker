"""Generates the synthetic test statements in tests/fixtures/.

Run with: .venv/bin/python scripts/generate_test_statements.py

These are synthetic, invented data only (Testing Requirements: "no real
customer data"). Each PDF has a real text layer, written in the same
plain row format the fallback parser understands (see parsing.py) so the
full extract -> mask -> parse -> validate pipeline can be exercised without
an ANTHROPIC_API_KEY configured. In production the AI step (not this
regex fallback) is what would handle each bank's real, varied layout.
"""
import os
from fpdf import FPDF

OUT_DIR = os.path.join(os.path.dirname(__file__), '..', 'tests', 'fixtures')


def make_pdf(filename, lines):
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font('Courier', size=11)
    for line in lines:
        pdf.cell(0, 7, text=line, new_x='LMARGIN', new_y='NEXT')
    pdf.output(os.path.join(OUT_DIR, filename))


def row(date, desc, amount, balance):
    # pdfplumber's text extraction collapses runs of rendered whitespace
    # down to single spaces, so a column format needs an explicit
    # delimiter rather than relying on multiple spaces surviving.
    sign = '' if amount >= 0 else '-'
    return f'{date} | {desc} | {sign}${abs(amount):,.2f} | ${balance:,.2f}'


# 1) Riverside Bank — clean statement, balances reconcile exactly.
make_pdf('riverside_bank.pdf', [
    'RIVERSIDE BANK - Chequing Statement',
    'Account holder: Jordan Patel',
    'Period: 2026-08-01 to 2026-08-31',
    'Opening Balance: $1,200.00',
    '',
    row('2026-08-03', 'GROCERY MART #44', -54.20, 1145.80),
    row('2026-08-05', 'PAYROLL DEPOSIT', 1500.00, 2645.80),
    row('2026-08-10', 'ELECTRIC CO UTILITY BILL', -112.35, 2533.45),
    row('2026-08-18', 'COFFEE SHOP', -6.75, 2526.70),
    row('2026-08-27', 'TRANSFER TO SAVINGS', -300.00, 2226.70),
    '',
    'Closing Balance: $2,226.70',
])

# 2) Northwind Credit Union — different header wording, same row shape.
make_pdf('northwind_credit_union.pdf', [
    'NORTHWIND CREDIT UNION',
    'Member Statement of Account',
    'Period: 2026-09-01 to 2026-09-30',
    'Opening Balance: $480.50',
    '',
    row('2026-09-02', 'RENT PAYMENT', -950.00, -469.50),
    row('2026-09-04', 'PART-TIME PAY', 600.00, 130.50),
    row('2026-09-15', 'STREAMING SERVICE', -15.99, 114.51),
    row('2026-09-28', 'E-TRANSFER RECEIVED', 200.00, 314.51),
    '',
    'Closing Balance: $314.51',
])

# 3) Harbor Trust — deliberately has a bad balance and an out-of-period
# date, to exercise the row-flagging path.
make_pdf('harbor_trust_flagged.pdf', [
    'HARBOR TRUST BANK',
    'Statement Period: 2026-07-01 to 2026-07-31',
    'Opening Balance: $2,000.00',
    '',
    row('2026-07-05', 'GROCERY MART #44', -80.00, 1920.00),
    row('2026-07-12', 'PAYROLL DEPOSIT', 1800.00, 3720.00),
    row('2026-06-29', 'LATE FEE REVERSAL', 25.00, 3745.00),      # date before period -> flagged
    row('2026-07-20', 'CAR INSURANCE', -150.00, 3600.00),        # balance should be 3595.00 -> flagged
    '',
    'Closing Balance: $3,600.00',
])

# 4) A scanned page with no extractable text layer (OCR not available in
# this environment), to exercise the "parsing fails -> save nothing,
# show a retry message" failure path.
pdf = FPDF()
pdf.add_page()
pdf.output(os.path.join(OUT_DIR, 'blank_scanned.pdf'))

print('Wrote fixtures to', os.path.abspath(OUT_DIR))

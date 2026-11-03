"""Contribution rules for investment and savings accounts (US-18, US-19, US-20).

Pure functions, no storage: app.py hands in the account doc and its logged
contributions/withdrawals, and gets back a row per year from the account's
start year up to the requested year.

Every Canadian account type falls into one of three kinds:

- "annual" room (TFSA, FHSA, RRSP): new room each Jan 1, tracked year by year.
  - TFSA: each Jan 1 adds that year's annual limit, plus everything withdrawn
    the previous year. Unused room carries forward without limit. A withdrawal
    never restores room in the same year.
  - FHSA: $8,000 of new room per year, and at most $8,000 of unused room
    carries into the next year (so at most $16,000 in one year). Contributions
    over the whole life of the account are capped at $40,000. Withdrawals never
    restore room.
  - RRSP: new room depends on last year's income (18%, up to a yearly maximum),
    so the user enters it as `annual_room` from their Notice of Assessment.
    Unused room carries forward without limit, withdrawals never restore it,
    and CRA only charges the penalty tax beyond a $2,000 cushion.
- "lifetime" cap (RESP, RDSP): no yearly room, just a cap on everything ever
  contributed. RESP rows also show progress toward the $2,500 a year that
  earns the full 20% Canada Education Savings Grant.
- "none" (LIRA, RRIF, non-registered): no contribution limits; the log is a
  record of money in and out.

The user enters `starting_room` = the room available on Jan 1 of
`start_year` (from CRA My Account), which already reflects every year before
that. Lifetime-capped accounts (and FHSA) also take `prior_contributions`
(made before tracking started) so the cap is applied correctly.
"""

# type -> label, full name, kind, first year it existed (earliest start_year)
# and, for capped types, the limit. Order is the order shown in the UI.
ACCOUNT_TYPES = {
    'tfsa': {'label': 'TFSA', 'name': 'Tax-Free Savings Account', 'kind': 'annual', 'first_year': 2009},
    'fhsa': {'label': 'FHSA', 'name': 'First Home Savings Account', 'kind': 'annual', 'first_year': 2023},
    'rrsp': {'label': 'RRSP', 'name': 'Registered Retirement Savings Plan', 'kind': 'annual', 'first_year': 1957},
    'resp': {'label': 'RESP', 'name': 'Registered Education Savings Plan', 'kind': 'lifetime', 'first_year': 1974,
             'lifetime_limit': 50000},
    'rdsp': {'label': 'RDSP', 'name': 'Registered Disability Savings Plan', 'kind': 'lifetime', 'first_year': 2008,
             'lifetime_limit': 200000},
    'lira': {'label': 'LIRA', 'name': 'Locked-In Retirement Account', 'kind': 'none', 'first_year': 1950},
    'rrif': {'label': 'RRIF', 'name': 'Registered Retirement Income Fund', 'kind': 'none', 'first_year': 1950},
    'non_registered': {'label': 'Non-registered', 'name': 'Regular investment or savings account', 'kind': 'none',
                       'first_year': 1950},
}
REGISTERED_TYPES = set(ACCOUNT_TYPES)

# TFSA annual dollar limit by year. Years past the last entry reuse it until
# CRA announces the next (indexed) figure — add it here when it does.
TFSA_ANNUAL_LIMITS = {
    2009: 5000, 2010: 5000, 2011: 5000, 2012: 5000,
    2013: 5500, 2014: 5500, 2015: 10000,
    2016: 5500, 2017: 5500, 2018: 5500,
    2019: 6000, 2020: 6000, 2021: 6000, 2022: 6000,
    2023: 6500, 2024: 7000, 2025: 7000, 2026: 7000,
}

FHSA_ANNUAL_LIMIT = 8000
FHSA_CARRYFORWARD_MAX = 8000
FHSA_LIFETIME_LIMIT = 40000

# RRSP over-contributions only attract the 1%/month tax beyond this cushion.
RRSP_OVER_CONTRIBUTION_BUFFER = 2000

# RESP: the 20% CESG is paid on up to $2,500 of contributions a year.
RESP_GRANT_ELIGIBLE = 2500
RESP_GRANT_RATE = 0.20


def tfsa_annual_limit(year):
    if year in TFSA_ANNUAL_LIMITS:
        return TFSA_ANNUAL_LIMITS[year]
    known = sorted(TFSA_ANNUAL_LIMITS)
    return TFSA_ANNUAL_LIMITS[known[-1] if year > known[-1] else known[0]]


def _totals_by_year(transactions):
    contributions, withdrawals = {}, {}
    for t in transactions:
        try:
            year = int((t.get('date') or '')[:4])
        except ValueError:
            continue
        amount = float(t.get('amount') or 0)
        bucket = contributions if t.get('type') == 'contribution' else withdrawals
        bucket[year] = bucket.get(year, 0.0) + amount
    return contributions, withdrawals


def compute_room(account, transactions, through_year):
    """Year-by-year rows for `account` from its start_year to `through_year`.

    Every row has year, contributed and withdrawn. Then by kind:
    - annual: room (available on Jan 1, before that year's activity),
      remaining (room - contributed; negative means over-contributed) and
      `available`. FHSA rows also carry lifetime_contributed and
      lifetime_remaining (as of the end of that year), and `available` is the
      smaller of the year's remaining room and the lifetime remaining.
      TFSA rows carry `restored_next_year` (the year's withdrawals, which come
      back as room the following Jan 1).
    - lifetime: room = what's left under the cap on Jan 1, remaining and
      available after the year's contributions, lifetime_contributed and
      lifetime_remaining. RESP rows add grant_eligible / grant_earned /
      grant_room_left for the year.
    - none: net (contributed - withdrawn) and running total_net.
    """
    acc_type = account.get('type')
    kind = ACCOUNT_TYPES[acc_type]['kind']
    start_year = int(account.get('start_year'))
    contributions, withdrawals = _totals_by_year(transactions)
    years = range(start_year, max(start_year, through_year) + 1)

    if kind == 'lifetime':
        return _lifetime_rows(account, contributions, withdrawals, years)
    if kind == 'none':
        rows, total = [], 0.0
        for year in years:
            contributed, withdrawn = contributions.get(year, 0.0), withdrawals.get(year, 0.0)
            total += contributed - withdrawn
            rows.append({'year': year, 'contributed': round(contributed, 2), 'withdrawn': round(withdrawn, 2),
                         'net': round(contributed - withdrawn, 2), 'total_net': round(total, 2)})
        return rows

    is_fhsa = acc_type == 'fhsa'
    lifetime = float(account.get('prior_contributions') or 0) if is_fhsa else 0.0

    rows = []
    room = float(account.get('starting_room') or 0)
    for year in years:
        if year > start_year:
            prev = rows[-1]
            if is_fhsa:
                carry = min(max(prev['remaining'], 0.0), FHSA_CARRYFORWARD_MAX)
                room = FHSA_ANNUAL_LIMIT + carry
            elif acc_type == 'rrsp':
                room = prev['remaining'] + float(account.get('annual_room') or 0)
            else:
                room = prev['remaining'] + tfsa_annual_limit(year) + prev['withdrawn']

        contributed = contributions.get(year, 0.0)
        withdrawn = withdrawals.get(year, 0.0)
        remaining = room - contributed
        row = {
            'year': year,
            'room': round(room, 2),
            'contributed': round(contributed, 2),
            'withdrawn': round(withdrawn, 2),
            'remaining': round(remaining, 2),
        }
        if is_fhsa:
            lifetime += contributed
            lifetime_remaining = FHSA_LIFETIME_LIMIT - lifetime
            row['lifetime_contributed'] = round(lifetime, 2)
            row['lifetime_remaining'] = round(lifetime_remaining, 2)
            row['available'] = round(min(remaining, lifetime_remaining), 2)
        else:
            if acc_type == 'tfsa':
                row['restored_next_year'] = round(withdrawn, 2)
            row['available'] = row['remaining']
        rows.append(row)
    return rows


def _lifetime_rows(account, contributions, withdrawals, years):
    limit = ACCOUNT_TYPES[account['type']]['lifetime_limit']
    lifetime = float(account.get('prior_contributions') or 0)
    rows = []
    for year in years:
        contributed, withdrawn = contributions.get(year, 0.0), withdrawals.get(year, 0.0)
        room = limit - lifetime
        lifetime += contributed  # withdrawals never give lifetime room back
        row = {
            'year': year,
            'room': round(room, 2),
            'contributed': round(contributed, 2),
            'withdrawn': round(withdrawn, 2),
            'remaining': round(room - contributed, 2),
            'available': round(room - contributed, 2),
            'lifetime_contributed': round(lifetime, 2),
            'lifetime_remaining': round(limit - lifetime, 2),
        }
        if account['type'] == 'resp':
            eligible = min(contributed, RESP_GRANT_ELIGIBLE)
            row['grant_eligible'] = round(eligible, 2)
            row['grant_earned'] = round(eligible * RESP_GRANT_RATE, 2)
            row['grant_room_left'] = round(RESP_GRANT_ELIGIBLE - eligible, 2)
        rows.append(row)
    return rows


def over_contribution(account, transactions, from_year, through_year):
    """Largest shortfall (positive dollars) in any year from `from_year` on.

    A past contribution shrinks every later year's room too, so the check
    looks at all years it can affect, not just its own. For an RRSP it's the
    shortfall beyond the $2,000 cushion, since that's what CRA taxes.
    """
    if ACCOUNT_TYPES[account.get('type')]['kind'] == 'none':
        return 0.0
    buffer = RRSP_OVER_CONTRIBUTION_BUFFER if account.get('type') == 'rrsp' else 0
    worst = 0.0
    for row in compute_room(account, transactions, through_year):
        if row['year'] >= from_year:
            worst = max(worst, -row['available'] - buffer)
    return round(worst, 2)

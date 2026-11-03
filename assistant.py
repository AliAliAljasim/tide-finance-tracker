"""In-app AI assistant: answers questions about the user's money and can
propose adding an account.

Small local models are unreliable at arithmetic and at multi-step tool use,
so instead of tools the model gets a pre-computed JSON snapshot of the user's
finances (totals already summed) and replies in a fixed JSON shape. Adding an
account is only ever a *proposal*: app.py validates it and the user confirms
it in the UI, which then calls the normal accounts API.

Pure functions apart from `ask`, which calls the local model via llm.py.
"""
import json

import llm

MAX_HISTORY = 12      # most recent messages sent to the model
MAX_MESSAGE_CHARS = 2000
CONTEXT_TOKENS = 8192  # snapshot + history needs more than Ollama's default window
RECENT_TRANSACTIONS = 25
SPENDING_MONTHS = 12

BANK_TYPES = ['chequing', 'savings', 'credit_card']

ACTION_KINDS = ['none', 'add_bank_account', 'add_investing_account']

RESPONSE_SCHEMA = {
    'type': 'object',
    'properties': {
        'reply': {'type': 'string'},
        'action': {
            'type': 'object',
            'properties': {
                'kind': {'type': 'string', 'enum': ACTION_KINDS},
                'name': {'type': 'string'},
                'account_type': {'type': 'string'},
                'institution': {'type': 'string'},
                'amount': {'type': 'number'},
            },
            'required': ['kind', 'name', 'account_type', 'institution', 'amount'],
        },
    },
    'required': ['reply', 'action'],
}


def system_prompt(snapshot, investing_types):
    type_lines = '\n'.join(f"  - {t}: {m['label']} ({m['name']}), {m['kind']}" for t, m in investing_types.items())
    return f"""You are the assistant inside "Finance", a personal finance app for someone in Canada.
Answer questions using ONLY the JSON snapshot of their data below. Amounts are CAD.
Every total is already calculated, so quote the numbers from the snapshot rather than doing your own math.
If the snapshot doesn't contain the answer (for example a month with no data), say so plainly and suggest uploading a statement.
Be brief and friendly: one to three short sentences, or a short list. Use plain text; **bold** is allowed for key figures.
Never invent accounts, transactions or numbers. You can't move money or change anything except adding an account as described below.

You can propose adding ONE account when the user asks you to. Set action.kind:
- "add_bank_account" for a chequing, savings or credit card account they upload statements for.
  account_type is one of: chequing, savings, credit_card. amount is the current balance (for a credit card, the amount owed).
- "add_investing_account" for an investment or registered account. account_type is one of:
{type_lines}
  amount means: for "annual" types (tfsa, fhsa, rrsp) the contribution room available this year; for "lifetime" types
  (resp, rdsp) contributions already made; for "none" types it's ignored, use 0. This app tracks room and contributions,
  not market value, so if they give a balance for a registered account, explain that and use 0 unless they gave room.
- "name" is a short account name like "Questrade TFSA". "institution" is the bank or broker, or "" if unknown.
The user will see a confirmation card, so in "reply" say what you're about to add and ask them to confirm below.
When not adding an account, set action.kind to "none", name/account_type/institution to "" and amount to 0.

Data snapshot:
{json.dumps(snapshot, separators=(',', ':'))}"""


def build_snapshot(today, user_name, accounts, investing_accounts, budget_report, transactions, categories_by_id,
                   transfers_id):
    """Everything the model may talk about, pre-aggregated.

    `transactions` are the user's confirmed bank transactions; `investing_accounts`
    are already passed through app.with_room (they carry `current`).
    """
    this_month = today.strftime('%Y-%m')
    months = _last_months(today, SPENDING_MONTHS)
    spending = {m: {} for m in months}
    income = {m: 0.0 for m in months}
    for t in transactions:
        month = (t.get('date') or '')[:7]
        if month not in spending or t.get('category_id') == transfers_id:
            continue
        amount = float(t.get('amount') or 0)
        if t.get('type') == 'debit':
            cat = categories_by_id.get(t.get('category_id'), {}).get('name', 'Other')
            spending[month][cat] = spending[month].get(cat, 0.0) + amount
        else:
            income[month] += amount

    monthly = []
    for m in months:
        cats = {k: round(v, 2) for k, v in sorted(spending[m].items(), key=lambda kv: -kv[1])}
        if cats or income[m]:
            total = round(sum(cats.values()), 2)
            monthly.append({'month': m, 'income': round(income[m], 2), 'spending_total': total,
                            'net': round(income[m] - total, 2), 'spending_by_category': cats})

    accounts_by_id = {a['_id']: a.get('name', '') for a in accounts}
    recent = sorted(transactions, key=lambda t: t.get('date', ''), reverse=True)[:RECENT_TRANSACTIONS]

    return {
        'today': today.isoformat(),
        'user_first_name': (user_name or '').split(' ')[0],
        'bank_accounts': [{
            'name': a.get('name'), 'type': a.get('type'), 'institution': a.get('institution', ''),
            # A credit card balance is what's owed, so it shows as negative.
            'balance': round((-1 if a.get('type') == 'credit_card' else 1) * float(a.get('current_balance') or 0), 2),
        } for a in accounts],
        'investing_accounts': [_investing_summary(a) for a in investing_accounts],
        'budgets_this_month': {
            'month': this_month,
            'categories': [{k: b[k] for k in ('category', 'amount', 'spent', 'remaining', 'pct', 'status')}
                           for b in budget_report.get('budgets', [])],
            'totals': budget_report.get('totals', {}),
        },
        'monthly_summary': monthly,
        'recent_transactions': [{
            'date': t.get('date'), 'description': t.get('description'),
            'category': categories_by_id.get(t.get('category_id'), {}).get('name', 'Other'),
            'amount': round(float(t.get('amount') or 0), 2) * (1 if t.get('type') == 'credit' else -1),
            'account': accounts_by_id.get(t.get('account_id'), 'Unknown account'),
        } for t in recent],
    }


def _investing_summary(a):
    cur = a['current']
    out = {'name': a.get('name'), 'type': a.get('label'), 'institution': a.get('institution', ''),
           'year': cur['year'], 'contributed_this_year': cur['contributed'], 'withdrawn_this_year': cur['withdrawn']}
    if a['kind'] == 'annual':
        out['room_on_jan_1'] = cur['room']
        out['room_left_this_year'] = cur['available']
    if 'lifetime_contributed' in cur:
        out['lifetime_contributed'] = cur['lifetime_contributed']
        out['lifetime_limit'] = a.get('lifetime_limit')
        out['lifetime_room_left'] = cur['lifetime_remaining']
    if 'grant_earned' in cur:
        out['resp_grant_earned_this_year'] = cur['grant_earned']
        out['resp_contribution_left_for_full_grant'] = cur['grant_room_left']
    if a['kind'] == 'none':
        out['net_deposited_all_time'] = cur['total_net']
    return out


def _last_months(today, n):
    y, m = today.year, today.month
    out = []
    for _ in range(n):
        out.append(f'{y}-{m:02d}')
        m -= 1
        if m == 0:
            y, m = y - 1, 12
    return out


def clean_history(messages):
    """Keeps only well-formed user/assistant turns, trimmed, most recent last."""
    out = []
    for msg in messages if isinstance(messages, list) else []:
        if not isinstance(msg, dict) or msg.get('role') not in ('user', 'assistant'):
            continue
        content = str(msg.get('content') or '').strip()[:MAX_MESSAGE_CHARS]
        if content:
            out.append({'role': msg['role'], 'content': content})
    return out[-MAX_HISTORY:]


def ask(history, snapshot, investing_types):
    """Returns {'reply': str, 'action': dict} from the model."""
    messages = [{'role': 'system', 'content': system_prompt(snapshot, investing_types)}] + history
    result = llm.chat(messages, RESPONSE_SCHEMA, temperature=0.2, num_ctx=CONTEXT_TOKENS)
    reply = str(result.get('reply') or '').strip()
    if not reply:
        raise llm.LLMError('The model returned an empty reply.')
    action = result.get('action') if isinstance(result.get('action'), dict) else {}
    return {'reply': reply, 'action': action}

// Dashboard: one screen that pulls from the accounts, summary, budgets,
// investing and statements APIs. Each section loads on its own so a slow or
// failing request only affects its own card.

function escapeHtml(str) {
    const div = document.createElement('div');
    div.textContent = str == null ? '' : String(str);
    return div.innerHTML;
}

function money(n) {
    const v = Number(n || 0);
    return (v < 0 ? '−$' : '$') + Math.abs(v).toLocaleString('en-CA', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function monthKey(offset) {
    const d = new Date();
    d.setDate(1);
    d.setMonth(d.getMonth() + offset);
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`;
}

async function getJson(url) {
    const res = await fetch(url);
    const data = await res.json();
    if (!res.ok || data.error) throw new Error(data.error || res.statusText);
    return data;
}

function showError(id) {
    const el = document.getElementById(id);
    const cls = el.closest('.card-flush') ? 'dash-empty list-empty' : 'dash-empty';
    el.innerHTML = `<p class="${cls}">Couldn&rsquo;t load this right now. Try refreshing.</p>`;
}

function meter(pct, tone) {
    return `<div class="bar"><span class="${tone}" style="width:${Math.max(0, Math.min(pct, 100))}%;"></span></div>`;
}

const ACCOUNT_ICONS = { chequing: 'landmark', savings: 'piggy-bank', credit_card: 'credit-card' };
const ACCOUNT_TYPE_LABELS = { chequing: 'Chequing', savings: 'Savings', credit_card: 'Credit card' };
const MONTH_NAME = new Date().toLocaleDateString('en-CA', { month: 'long' });

function shortDate(iso) {
    if (!iso) return '';
    const d = new Date(iso.slice(0, 10) + 'T00:00:00');
    return isNaN(d) ? iso : d.toLocaleDateString('en-CA', { month: 'short', day: 'numeric', year: 'numeric' });
}

// ── Net worth + accounts ────────────────────────────────────────────────

// A credit card's balance is what's owed, so it shows (and counts) as negative.
function signedBalance(a) {
    return (a.type === 'credit_card' ? -1 : 1) * Number(a.current_balance || 0);
}

function accountRow(a, stmts) {
    const bal = signedBalance(a);
    const last = stmts.map(s => s.period_end || (s.confirmed_at || '').slice(0, 10)).filter(Boolean).sort().pop();
    const meta = [a.institution, ACCOUNT_TYPE_LABELS[a.type]].filter(Boolean).map(escapeHtml).join(' · ');
    return `
    <div class="acct-row">
        <button type="button" class="acct-toggle" aria-expanded="false">
            <span class="row-icon" aria-hidden="true"><i class="icon-${ACCOUNT_ICONS[a.type] || 'wallet'}"></i></span>
            <span class="row-main">
                <span class="row-title">${escapeHtml(a.name)}</span>
                <span class="row-meta">${meta}</span>
            </span>
            <span class="row-amount ${bal < 0 ? 'neg' : ''}">${money(bal)}</span>
            <i class="icon-chevron-down acct-chev" aria-hidden="true"></i>
        </button>
        <div class="acct-detail" hidden>
            <span>${stmts.length ? `${stmts.length} statement${stmts.length === 1 ? '' : 's'} confirmed` : 'No confirmed statements yet'}</span>
            ${last ? `<span>Last statement ${escapeHtml(shortDate(last))}</span>` : ''}
            <a href="/accounts/${encodeURIComponent(a._id)}" class="btn btn-outline btn-sm">View transactions</a>
        </div>
    </div>`;
}

async function loadAccounts() {
    const [accData, stmtData] = await Promise.all([
        getJson('/api/accounts'),
        getJson('/api/statements').catch(() => ({ statements: [] })),
    ]);
    const accounts = accData.accounts || [];
    const confirmed = (stmtData.statements || []).filter(s => s.status === 'confirmed');

    const balances = accounts.map(signedBalance);
    const assets = balances.filter(b => b > 0).reduce((s, b) => s + b, 0);
    const debts = balances.filter(b => b < 0).reduce((s, b) => s + b, 0);
    document.getElementById('netValue').innerHTML = moneyHtml(assets + debts);

    if (assets || debts) {
        document.getElementById('assetsValue').textContent = money(assets);
        document.getElementById('debtsValue').textContent = money(debts);
        const split = document.getElementById('netSplit');
        split.querySelector('.assets').style.width = (assets / (assets - debts) * 100) + '%';
        split.classList.toggle('no-debt', !debts);
        split.classList.remove('hidden');
        document.getElementById('netLegend').classList.remove('hidden');
    }

    const latest = confirmed.map(s => s.period_end).filter(Boolean).sort().pop();
    if (latest) document.getElementById('dashSub').textContent = `Balances from statements confirmed through ${shortDate(latest)}.`;

    const meta = document.getElementById('accountsMeta');
    const list = document.getElementById('accountsList');
    if (!accounts.length) {
        meta.textContent = 'Add account';
        list.innerHTML = '<p class="list-empty dash-empty">No accounts yet. <a href="/accounts">Add your first account</a>, then upload a statement for it.</p>';
        return;
    }
    meta.textContent = `${accounts.length} account${accounts.length === 1 ? '' : 's'}`;
    list.innerHTML = accounts.map(a => accountRow(a, confirmed.filter(s => s.account_id === a._id))).join('');
}

document.getElementById('accountsList').addEventListener('click', e => {
    const btn = e.target.closest('.acct-toggle');
    if (!btn) return;
    const open = btn.getAttribute('aria-expanded') !== 'true';
    btn.setAttribute('aria-expanded', String(open));
    btn.nextElementSibling.hidden = !open;
});

// ── This month's cash flow ──────────────────────────────────────────────

async function loadFlow() {
    const months = (await getJson(`/api/summary/monthly?from=${monthKey(0)}&to=${monthKey(0)}`)).months || [];
    const cur = months.find(m => m.month === monthKey(0));
    if (!cur || (!cur.income && !cur.expenses)) return;
    const badge = document.getElementById('flowBadge');
    badge.textContent = `${moneySigned(cur.net)} in ${MONTH_NAME}`;
    badge.classList.add(cur.net < 0 ? 'badge-danger' : 'badge-positive');
    badge.classList.remove('hidden');
}

function moneySigned(n) {
    return (n > 0 ? '+' : '') + money(n);
}

// ── Budgets: every category with what's left ────────────────────────────

async function loadBudgets() {
    const data = await getJson(`/api/budgets?month=${monthKey(0)}`);
    const el = document.getElementById('budgetsList');
    const budgets = data.budgets || [];
    document.getElementById('budgetsTitle').textContent = `${MONTH_NAME} budgets`;
    if (!budgets.length) {
        document.getElementById('budgetsMeta').textContent = 'Set up';
        el.innerHTML = '<p class="dash-empty">No budgets yet. <a href="/budgets">Set a monthly limit</a> for a category and you&rsquo;ll be warned at 80% and 100%.</p>';
        return;
    }
    const { amount, spent } = data.totals;
    document.getElementById('budgetsMeta').textContent = `${money(spent)} of ${money(amount)}`;
    el.innerHTML = budgets.map(b => `
        <div>
            <div class="mini-row-head">
                <strong>${escapeHtml(b.category)}</strong>
                <span class="${b.status === 'over' ? 'neg' : ''}">${b.remaining < 0 ? `${money(-b.remaining)} over` : `${money(b.remaining)} left`}</span>
            </div>
            ${meter(b.pct, b.status)}
        </div>`).join('');
}

// ── Recent transactions ─────────────────────────────────────────────────

async function loadRecent() {
    const rows = (await getJson('/api/transactions/recent?limit=6')).transactions || [];
    const el = document.getElementById('recentList');
    if (!rows.length) {
        el.innerHTML = '<p class="list-empty dash-empty">No confirmed transactions yet. <a href="/upload">Upload a statement</a> to get started.</p>';
        return;
    }
    el.innerHTML = rows.map(t => {
        const credit = t.type === 'credit';
        return `
        <div class="list-row compact">
            ${categoryIconHtml(t.category_name, t.category_kind === 'income')}
            <span class="row-main">
                <span class="row-title" style="font-size:14px;">${escapeHtml(t.description || 'No description')}</span>
                <span class="row-meta">${escapeHtml(shortDate(t.date).replace(/, \d{4}$/, ''))} · ${escapeHtml(t.category_name)} · ${escapeHtml(t.account_name)}</span>
            </span>
            <span class="row-amount ${credit ? 'pos' : ''}" style="font-size:14px;">${credit ? '+' : '−'}${money(t.amount).replace('−', '')}</span>
        </div>`;
    }).join('');
}

// ── Investing ───────────────────────────────────────────────────────────

async function loadRegistered() {
    const accounts = (await getJson('/api/registered')).accounts || [];
    const el = document.getElementById('registeredList');
    if (!accounts.length) {
        el.innerHTML = '<p class="dash-empty">No investment accounts yet. <a href="/investing">Add a TFSA, RRSP, RESP</a> or any other account to track room and contributions.</p>';
        return;
    }
    el.innerHTML = accounts.map(a => {
        const cur = a.current;
        const head = `
            <div class="mini-row-head">
                <span style="display:flex;align-items:center;gap:8px;min-width:0;color:var(--text-primary);">
                    ${investBadge(a)}
                    <a href="/investing/${a._id}" class="row-title" style="font-size:14px;">${escapeHtml(a.name)}</a>
                </span>`;
        if (a.kind === 'none') {
            return `<div>${head}<span>${money(cur.total_net)} deposited</span></div></div>`;
        }
        const over = cur.available < 0;
        const used = a.kind === 'lifetime'
            ? cur.lifetime_contributed / a.lifetime_limit * 100
            : (cur.room > 0 ? cur.contributed / cur.room * 100 : (cur.contributed > 0 ? 100 : 0));
        const left = a.kind === 'lifetime' ? 'lifetime room left' : 'left';
        return `
        <div>
            ${head}
                <span class="${over ? 'neg' : ''}">${over ? `${money(-cur.available)} over` : `${money(cur.available)} ${left}`}</span>
            </div>
            ${meter(used, over ? 'over' : 'accent')}
        </div>`;
    }).join('');
}

// ── Statements waiting for review ───────────────────────────────────────

async function loadReviewNotice() {
    const statements = (await getJson('/api/statements')).statements || [];
    const ready = statements.filter(s => s.status === 'parsed');
    if (!ready.length) return;
    document.getElementById('reviewNoticeText').innerHTML = ready.length === 1
        ? `Your <strong>${escapeHtml(ready[0].account_name)}</strong> statement is parsed and ready to review. It won&rsquo;t count in your totals until you confirm it.`
        : `<strong>${ready.length} statements</strong> are parsed and ready to review. They won&rsquo;t count in your totals until you confirm them.`;
    document.getElementById('reviewNoticeLink').href = ready.length === 1 ? `/review/${ready[0]._id}` : '/upload';
    document.getElementById('reviewNotice').classList.remove('hidden');
}

const hour = new Date().getHours();
const greetingEl = document.getElementById('dashGreeting');
const greeting = hour < 12 ? 'Good morning' : hour < 18 ? 'Good afternoon' : 'Good evening';
greetingEl.textContent = greetingEl.dataset.name ? `${greeting}, ${greetingEl.dataset.name}` : greeting;

loadAccounts().catch(() => { document.getElementById('netValue').textContent = '—'; showError('accountsList'); });
loadFlow().catch(() => {});
loadBudgets().catch(() => showError('budgetsList'));
loadRecent().catch(() => showError('recentList'));
loadRegistered().catch(() => showError('registeredList'));
loadReviewNotice().catch(() => {});

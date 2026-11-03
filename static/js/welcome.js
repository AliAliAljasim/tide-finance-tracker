// Onboarding after sign-up: name → bank accounts → budgets → done.
// Every step saves through the same APIs the rest of the app uses, and every
// step after the name can be skipped. The current step lives in the URL hash so a refresh
// (or the browser's back button) keeps your place.

const TYPE_LABELS = { chequing: 'Chequing', savings: 'Savings', credit_card: 'Credit card' };
const TYPE_ICONS = { chequing: 'landmark', savings: 'piggy-bank', credit_card: 'credit-card' };
const SUGGESTED_BUDGETS = ['Groceries', 'Dining', 'Transportation', 'Shopping', 'Subscriptions'];
const LAST_STEP = 4;

const recap = { accounts: [] };

function escapeHtml(str) {
    const div = document.createElement('div');
    div.textContent = str == null ? '' : String(str);
    return div.innerHTML;
}

function money(n) {
    const v = Number(n || 0);
    return (v < 0 ? '−$' : '$') + Math.abs(v).toLocaleString('en-CA', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

async function api(url, method, body) {
    const res = await fetch(url, {
        method: method || 'GET',
        headers: body ? { 'Content-Type': 'application/json' } : {},
        body: body ? JSON.stringify(body) : undefined,
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok || data.error) throw new Error(data.error || 'Something went wrong. Please try again.');
    return data;
}

function showError(id, message) {
    const el = document.getElementById(id);
    el.textContent = message || '';
    el.classList.toggle('hidden', !message);
}

function setLoading(on) {
    document.getElementById('loadingOverlay').classList.toggle('hidden', !on);
}

// ── Step navigation ─────────────────────────────────────────────────────

const stepLoaders = { 2: loadAccounts, 3: loadBudgets, 4: renderRecap };

// A name is required (the server redirects every page here until there is
// one), so until it's saved the later steps and "Skip setup" stay locked.
let hasName = document.body.dataset.hasName === '1';

function currentStep() {
    const n = parseInt(location.hash.slice(1), 10);
    if (!hasName) return 1;
    return n >= 1 && n <= LAST_STEP ? n : 1;
}

function showStep(n) {
    document.querySelectorAll('.ob-step').forEach(s => s.classList.toggle('hidden', Number(s.dataset.step) !== n));
    document.querySelectorAll('.ob-steps li').forEach(li => {
        const step = Number(li.dataset.step);
        li.classList.toggle('current', step === n);
        li.classList.toggle('done', step < n);
        if (step === n) li.setAttribute('aria-current', 'step'); else li.removeAttribute('aria-current');
    });
    document.getElementById('obProgress').style.width = ((n - 1) / (LAST_STEP - 1) * 100) + '%';
    // On the last step there's nothing left to skip.
    document.getElementById('skipSetup').style.visibility = n === LAST_STEP || !hasName ? 'hidden' : '';
    if (stepLoaders[n]) stepLoaders[n]().catch(() => {});
    const focusTarget = document.querySelector(`.ob-step[data-step="${n}"] input:not([type=radio]), .ob-step[data-step="${n}"] h1`);
    if (focusTarget && focusTarget.tagName === 'INPUT') focusTarget.focus();
    window.scrollTo(0, 0);
}

function goTo(n) {
    if (currentStep() === n) showStep(n);
    else location.hash = String(n);
}

window.addEventListener('hashchange', () => showStep(currentStep()));
document.querySelectorAll('[data-back]').forEach(btn => btn.addEventListener('click', () => goTo(currentStep() - 1)));

// ── Step 1: name ────────────────────────────────────────────────────────

document.getElementById('nameForm').addEventListener('submit', async e => {
    e.preventDefault();
    showError('nameError');
    const name = document.getElementById('nameInput').value.trim();
    if (!name) {
        showError('nameError', 'Please enter your name.');
        return;
    }
    setLoading(true);
    try {
        await api('/api/profile', 'PUT', { name });
        hasName = true;
        goTo(2);
    } catch (err) {
        showError('nameError', err.message);
    } finally {
        setLoading(false);
    }
});

// ── Step 2: bank accounts ───────────────────────────────────────────────

function selectedType() {
    return document.querySelector('input[name="accountType"]:checked').value;
}

// A credit card's balance is what's owed, so the field reads differently.
function syncBalanceCopy() {
    const credit = selectedType() === 'credit_card';
    document.getElementById('balanceLabel').textContent = credit ? 'Balance owed' : 'Current balance';
    document.getElementById('balanceHint').textContent = credit
        ? 'What you owe on the card today, not your available credit.'
        : 'What’s in the account today. Confirmed statements update it from here.';
    document.getElementById('accountName').placeholder = {
        chequing: 'e.g. Everyday Chequing', savings: 'e.g. High-Interest Savings', credit_card: 'e.g. Cashback Visa',
    }[selectedType()];
}

document.querySelectorAll('input[name="accountType"]').forEach(r => r.addEventListener('change', syncBalanceCopy));

function renderAccounts() {
    const accounts = recap.accounts;
    document.getElementById('addedAccounts').classList.toggle('hidden', !accounts.length);
    document.getElementById('addedCount').textContent = `${accounts.length} added`;
    document.getElementById('accountFormTitle').textContent = accounts.length ? 'Add another account' : 'Add an account';
    document.getElementById('accountsNext').innerHTML = accounts.length
        ? 'Continue<i class="icon-arrow-right"></i>'
        : 'Skip for now<i class="icon-arrow-right"></i>';
    document.getElementById('addedList').innerHTML = accounts.map(a => {
        const bal = (a.type === 'credit_card' ? -1 : 1) * Number(a.current_balance || 0);
        const meta = [a.institution, TYPE_LABELS[a.type]].filter(Boolean).map(escapeHtml).join(' · ');
        return `
        <div class="list-row">
            <span class="row-icon" aria-hidden="true"><i class="icon-${TYPE_ICONS[a.type]}"></i></span>
            <span class="row-main">
                <span class="row-title">${escapeHtml(a.name)}</span>
                <span class="row-meta">${meta}</span>
            </span>
            <span class="row-amount ${bal < 0 ? 'neg' : ''}">${money(bal)}</span>
            <button type="button" class="icon-btn icon-btn-sm danger" data-remove="${escapeHtml(a._id)}" aria-label="Remove ${escapeHtml(a.name)}" title="Remove"><i class="icon-trash-2"></i></button>
        </div>`;
    }).join('');
}

async function loadAccounts() {
    recap.accounts = (await api('/api/accounts')).accounts || [];
    renderAccounts();
}

document.getElementById('accountForm').addEventListener('submit', async e => {
    e.preventDefault();
    showError('accountError');
    const nameEl = document.getElementById('accountName');
    const body = {
        name: nameEl.value.trim(),
        type: selectedType(),
        institution: document.getElementById('accountInstitution').value.trim(),
        opening_balance: document.getElementById('accountOpeningBalance').value || 0,
    };
    if (!body.name) {
        showError('accountError', 'Give the account a name.');
        nameEl.focus();
        return;
    }
    setLoading(true);
    try {
        const data = await api('/api/accounts', 'POST', body);
        recap.accounts.push(data.account);
        renderAccounts();
        // Keep the institution: people often add several accounts from one bank.
        nameEl.value = '';
        document.getElementById('accountOpeningBalance').value = '';
        nameEl.focus();
    } catch (err) {
        showError('accountError', err.message);
    } finally {
        setLoading(false);
    }
});

document.getElementById('addedList').addEventListener('click', async e => {
    const btn = e.target.closest('[data-remove]');
    if (!btn) return;
    setLoading(true);
    try {
        await api(`/api/accounts/${encodeURIComponent(btn.dataset.remove)}`, 'DELETE');
        recap.accounts = recap.accounts.filter(a => a._id !== btn.dataset.remove);
        renderAccounts();
    } catch (err) {
        showError('accountError', err.message);
    } finally {
        setLoading(false);
    }
});

document.getElementById('accountsNext').addEventListener('click', () => goTo(3));

// ── Step 3: budgets ─────────────────────────────────────────────────────

async function loadBudgets() {
    const month = new Date().toISOString().slice(0, 7);
    const [catData, budgetData] = await Promise.all([api('/api/categories'), api(`/api/budgets?month=${month}`)]);
    const existing = Object.fromEntries((budgetData.budgets || []).map(b => [b.category_id, b.amount]));
    const cats = SUGGESTED_BUDGETS
        .map(name => (catData.categories || []).find(c => c.name === name && c.kind === 'expense'))
        .filter(Boolean);
    document.getElementById('budgetRows').innerHTML = cats.map(c => `
        <label class="ob-budget-row">
            ${categoryIconHtml(c.name, false)}
            <span class="row-main">${escapeHtml(c.name)}</span>
            <span class="control"><span class="affix">$</span><input type="number" class="input mono" min="0" step="1" placeholder="Per month" data-category="${escapeHtml(c._id)}" value="${existing[c._id] ?? ''}" aria-label="${escapeHtml(c.name)} monthly budget"></span>
        </label>`).join('');
}

document.getElementById('budgetForm').addEventListener('submit', async e => {
    e.preventDefault();
    showError('budgetError');
    const filled = [...document.querySelectorAll('#budgetRows input')].filter(i => i.value !== '');
    if (filled.some(i => !(Number(i.value) > 0))) {
        showError('budgetError', 'Budgets need to be more than $0. Clear a field to skip that category.');
        return;
    }
    setLoading(true);
    try {
        await Promise.all(filled.map(i => api(`/api/budgets/${encodeURIComponent(i.dataset.category)}`, 'PUT', { amount: Number(i.value) })));
        goTo(4);
    } catch (err) {
        showError('budgetError', err.message);
    } finally {
        setLoading(false);
    }
});

// ── Step 4: recap ───────────────────────────────────────────────────────

async function renderRecap() {
    // Coming straight to #4 (e.g. after a refresh) means nothing is in memory yet.
    const [profile, accData, budgetData] = await Promise.all([
        api('/api/profile'), api('/api/accounts'), api(`/api/budgets?month=${new Date().toISOString().slice(0, 7)}`),
    ]);
    const first = (profile.name || '').split(' ')[0];
    document.getElementById('step4Title').textContent = first ? `You’re all set, ${first}` : 'You’re all set';
    const accounts = accData.accounts || [];
    const budgets = budgetData.budgets || [];
    const row = (done, text) => `<div class="ob-recap-row${done ? '' : ' skipped'}"><i class="icon-${done ? 'circle-check' : 'circle-dashed'}" aria-hidden="true"></i>${text}</div>`;
    document.getElementById('recap').innerHTML = [
        row(accounts.length, accounts.length
            ? `${accounts.length} account${accounts.length === 1 ? '' : 's'} added: ${accounts.map(a => escapeHtml(a.name)).join(', ')}`
            : 'No accounts yet. You can add them from <a href="/accounts">Accounts</a>.'),
        row(budgets.length, budgets.length
            ? `${budgets.length} monthly budget${budgets.length === 1 ? '' : 's'} set, ${money(budgetData.totals.amount)} in total`
            : 'No budgets yet. Set them any time from <a href="/budgets">Budgets</a>.'),
    ].join('');
}

syncBalanceCopy();
showStep(currentStep());

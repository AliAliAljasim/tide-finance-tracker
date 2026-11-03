function escapeHtml(str) {
    const div = document.createElement('div');
    div.textContent = str == null ? '' : String(str);
    return div.innerHTML;
}

function money(n) {
    const v = Number(n || 0);
    return (v < 0 ? '−$' : '$') + Math.abs(v).toLocaleString('en-CA', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function showToast(message, isError) {
    const toast = document.getElementById('toast');
    toast.textContent = message;
    toast.className = 'toast ' + (isError ? 'error' : 'success');
    setTimeout(() => toast.classList.add('hidden'), 3000);
}

function thisMonth() {
    const d = new Date();
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`;
}

const monthInput = document.getElementById('budgetMonth');
let budgets = [];
let spendingCategories = [];

// ── List ────────────────────────────────────────────────────────────────

async function loadBudgets() {
    const res = await fetch(`/api/budgets?month=${monthInput.value}`);
    const data = await res.json();
    if (data.error) {
        showToast(data.error, true);
        return;
    }
    budgets = data.budgets || [];

    const { amount, spent, remaining } = data.totals;
    const over = remaining < 0;
    const remainingEl = document.getElementById('totalRemaining');
    remainingEl.innerHTML = moneyHtml(Math.abs(remaining));
    remainingEl.className = 'money money-lg' + (over ? ' neg' : '');
    document.getElementById('totalCaption').textContent = amount > 0
        ? `${over ? 'over' : 'left of'} ${money(amount)} this month · ${money(spent)} spent`
        : 'No budgets set yet';
    const pct = amount > 0 ? spent / amount * 100 : 0;
    const totalFill = document.getElementById('totalBar').firstElementChild;
    totalFill.style.width = Math.min(pct, 100) + '%';
    totalFill.className = pct >= 100 ? 'over' : pct >= 80 ? 'warning' : 'ok';

    const alertsEl = document.getElementById('budgetAlertsList');
    const alerts = data.alerts || [];
    alertsEl.innerHTML = alerts.map(a => `<div class="alert-item ${a.level}"><span>${escapeHtml(a.message)}</span></div>`).join('');
    alertsEl.classList.toggle('hidden', alerts.length === 0);

    const list = document.getElementById('budgetList');
    if (budgets.length === 0) {
        list.innerHTML = '<p class="list-empty">No budgets yet. Add one to start tracking a category.</p>';
        return;
    }
    list.innerHTML = budgets.map(b => {
        const width = Math.min(b.pct, 100);
        const remainingText = b.remaining >= 0 ? `${money(b.remaining)} left` : `${money(-b.remaining)} over`;
        const tone = b.status === 'over' ? 'neg' : b.status === 'warning' ? 'warn' : 'muted';
        return `
        <div class="list-row">
            ${categoryIconHtml(b.category)}
            <div class="row-main" style="display:flex;flex-direction:column;gap:8px;">
                <div style="display:flex;justify-content:space-between;gap:12px;font-size:14px;">
                    <span style="font-weight:600;">${escapeHtml(b.category)}</span>
                    <span class="mono ${tone}">${Math.floor(b.pct)}% · ${remainingText} · ${money(b.spent)} of ${money(b.amount)}</span>
                </div>
                <div class="bar" role="progressbar" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${Math.round(b.pct)}"
                     aria-label="${escapeHtml(b.category)} budget used">
                    <span class="${b.status}" style="width:${width}%;"></span>
                </div>
            </div>
            <span class="row-actions">
                <button type="button" class="icon-btn edit-budget" data-id="${b.category_id}" aria-label="Edit ${escapeHtml(b.category)} budget"><i class="icon-pencil"></i></button>
                <button type="button" class="icon-btn danger delete-budget" data-id="${b.category_id}" data-name="${escapeHtml(b.category)}" aria-label="Remove ${escapeHtml(b.category)} budget"><i class="icon-trash-2"></i></button>
            </span>
        </div>`;
    }).join('');

    list.querySelectorAll('.edit-budget').forEach(btn => btn.addEventListener('click', () => openModal(btn.dataset.id)));
    list.querySelectorAll('.delete-budget').forEach(btn => btn.addEventListener('click', () => removeBudget(btn.dataset.id, btn.dataset.name)));
}

async function loadCategories() {
    const res = await fetch('/api/categories');
    const data = await res.json();
    spendingCategories = (data.categories || [])
        .filter(c => c.kind === 'expense' && c.name !== 'Transfers')
        .sort((a, b) => a.name.localeCompare(b.name));
}

// ── Set / edit modal ────────────────────────────────────────────────────

const modal = document.getElementById('budgetModal');
const form = document.getElementById('budgetForm');
const categorySelect = document.getElementById('budgetCategory');

function openModal(categoryId) {
    const existing = budgets.find(b => b.category_id === categoryId);
    const budgeted = new Set(budgets.map(b => b.category_id));
    // Adding offers only categories without a budget; editing locks the category.
    const options = existing
        ? spendingCategories.filter(c => c._id === categoryId)
        : spendingCategories.filter(c => !budgeted.has(c._id));
    if (!options.length) {
        showToast('Every spending category already has a budget.', true);
        return;
    }
    categorySelect.innerHTML = options.map(c => `<option value="${c._id}">${escapeHtml(c.name)}</option>`).join('');
    categorySelect.disabled = !!existing;
    document.getElementById('budgetAmount').value = existing ? existing.amount : '';
    document.getElementById('budgetModalTitle').textContent = existing ? 'Edit budget' : 'Add budget';
    document.getElementById('budgetFormError').classList.add('hidden');
    modal.classList.add('show');
}

function closeModal() { modal.classList.remove('show'); }

document.getElementById('addBudgetBtn').addEventListener('click', () => openModal(null));
document.getElementById('budgetModalClose').addEventListener('click', closeModal);
document.getElementById('budgetModalCancel').addEventListener('click', closeModal);

form.addEventListener('submit', async function (e) {
    e.preventDefault();
    const errEl = document.getElementById('budgetFormError');
    errEl.classList.add('hidden');
    const res = await fetch(`/api/budgets/${categorySelect.value}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ amount: document.getElementById('budgetAmount').value }),
    });
    const data = await res.json();
    if (data.error) {
        errEl.textContent = data.error;
        errEl.classList.remove('hidden');
        return;
    }
    closeModal();
    showToast('Budget saved.', false);
    loadBudgets();
    window.refreshBudgetAlerts && window.refreshBudgetAlerts();
});

async function removeBudget(categoryId, name) {
    if (!confirm(`Remove the ${name} budget?`)) return;
    await fetch(`/api/budgets/${categoryId}`, { method: 'DELETE' });
    showToast('Budget removed.', false);
    loadBudgets();
    window.refreshBudgetAlerts && window.refreshBudgetAlerts();
}

monthInput.value = thisMonth();
monthInput.addEventListener('change', () => { if (monthInput.value) loadBudgets(); });
loadCategories().then(loadBudgets);

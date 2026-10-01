const TYPE_LABELS = { chequing: 'Chequing', savings: 'Savings', credit_card: 'Credit card' };

function escapeHtml(str) {
    const div = document.createElement('div');
    div.textContent = str == null ? '' : String(str);
    return div.innerHTML;
}

function money(n) {
    const v = Number(n || 0);
    return (v < 0 ? '-$' : '$') + Math.abs(v).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function showToast(message, isError) {
    const toast = document.getElementById('toast');
    toast.textContent = message;
    toast.className = 'toast ' + (isError ? 'error' : 'success');
    setTimeout(() => toast.classList.add('hidden'), 3000);
}

async function loadAccounts() {
    const res = await fetch('/api/accounts');
    const data = await res.json();
    const grid = document.getElementById('accountsGrid');
    const accounts = data.accounts || [];
    if (accounts.length === 0) {
        grid.innerHTML = '<p class="muted">No accounts yet. Add one to start uploading statements.</p>';
        return;
    }
    grid.innerHTML = accounts.map(a => {
        const isCard = a.type === 'credit_card';
        const balanceClass = isCard ? (a.current_balance > 0 ? 'neg' : 'pos') : (a.current_balance < 0 ? 'neg' : 'pos');
        const balanceLabel = isCard ? 'Balance owed' : 'Current balance';
        return `
        <div class="card card-lg ledger-card account-card" style="width:280px;">
            <div class="label">${TYPE_LABELS[a.type] || a.type}</div>
            <a href="/accounts/${a._id}" class="link" style="font:600 20px var(--font-display);color:var(--ink);text-decoration:none;display:block;margin-top:4px;">${escapeHtml(a.name)}</a>
            <div class="muted" style="font-size:13px;margin-top:2px;">${escapeHtml(a.institution || 'No institution set')}</div>
            <div class="stat-value ${balanceClass}">${money(a.current_balance)}</div>
            <div class="stat-sub">${balanceLabel}</div>
            <div class="row" style="margin-top:16px;gap:8px;">
                <button type="button" class="btn btn-outline btn-sm edit-account" data-id="${a._id}">Edit</button>
                <button type="button" class="btn btn-ghost btn-sm delete-account" data-id="${a._id}" data-name="${escapeHtml(a.name)}">Delete</button>
            </div>
        </div>`;
    }).join('');

    grid.querySelectorAll('.edit-account').forEach(btn => btn.addEventListener('click', () => openEditModal(btn.dataset.id, accounts)));
    grid.querySelectorAll('.delete-account').forEach(btn => btn.addEventListener('click', () => confirmDelete(btn.dataset.id, btn.dataset.name)));
}

// ── Add / edit modal ───────────────────────────────────────────────────

const accountModal = document.getElementById('accountModal');
const accountForm = document.getElementById('accountForm');

function openAddModal() {
    document.getElementById('accountModalTitle').textContent = 'Add account';
    accountForm.reset();
    document.getElementById('accountId').value = '';
    document.getElementById('accountFormError').classList.add('hidden');
    accountModal.classList.add('show');
}

function openEditModal(id, accounts) {
    const account = accounts.find(a => a._id === id);
    if (!account) return;
    document.getElementById('accountModalTitle').textContent = 'Edit account';
    document.getElementById('accountId').value = account._id;
    document.getElementById('accountName').value = account.name;
    document.getElementById('accountType').value = account.type;
    document.getElementById('accountInstitution').value = account.institution || '';
    document.getElementById('accountOpeningBalance').value = account.opening_balance;
    document.getElementById('accountFormError').classList.add('hidden');
    accountModal.classList.add('show');
}

function closeAccountModal() {
    accountModal.classList.remove('show');
}

document.getElementById('addAccountBtn').addEventListener('click', openAddModal);
document.getElementById('accountModalClose').addEventListener('click', closeAccountModal);
document.getElementById('accountModalCancel').addEventListener('click', closeAccountModal);

accountForm.addEventListener('submit', async function (e) {
    e.preventDefault();
    const errEl = document.getElementById('accountFormError');
    errEl.classList.add('hidden');

    const id = document.getElementById('accountId').value;
    const payload = {
        name: document.getElementById('accountName').value.trim(),
        type: document.getElementById('accountType').value,
        institution: document.getElementById('accountInstitution').value.trim(),
        opening_balance: parseFloat(document.getElementById('accountOpeningBalance').value || '0'),
    };

    const url = id ? `/api/accounts/${id}` : '/api/accounts';
    const method = id ? 'PUT' : 'POST';
    const res = await fetch(url, { method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
    const data = await res.json();
    if (data.error) {
        errEl.textContent = data.error;
        errEl.classList.remove('hidden');
        return;
    }
    closeAccountModal();
    showToast(id ? 'Account updated.' : 'Account added.', false);
    loadAccounts();
});

// ── Delete ──────────────────────────────────────────────────────────────

const deleteModal = document.getElementById('deleteConfirmModal');
let pendingDeleteId = null;

function confirmDelete(id, name) {
    pendingDeleteId = id;
    attemptDelete(id, false);
}

async function attemptDelete(id, force) {
    const res = await fetch(`/api/accounts/${id}${force ? '?force=true' : ''}`, { method: 'DELETE' });
    const data = await res.json();
    if (data.confirm_required) {
        document.getElementById('deleteConfirmText').textContent =
            `This account has ${data.transaction_count} transaction(s). Deleting it also deletes those transactions. Delete anyway?`;
        deleteModal.classList.add('show');
        return;
    }
    deleteModal.classList.remove('show');
    if (data.error) {
        showToast(data.error, true);
        return;
    }
    showToast('Account deleted.', false);
    loadAccounts();
}

document.getElementById('deleteModalConfirm').addEventListener('click', () => attemptDelete(pendingDeleteId, true));
document.getElementById('deleteModalCancel').addEventListener('click', () => deleteModal.classList.remove('show'));
document.getElementById('deleteModalClose').addEventListener('click', () => deleteModal.classList.remove('show'));

loadAccounts();

const TYPE_LABELS = { chequing: 'Chequing', savings: 'Savings', credit_card: 'Credit card' };
const TYPE_ICONS = { chequing: 'landmark', savings: 'piggy-bank', credit_card: 'credit-card' };

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

async function loadAccounts() {
    const res = await fetch('/api/accounts');
    const data = await res.json();
    const grid = document.getElementById('accountsList');
    const accounts = data.accounts || [];
    // A credit card's balance is what's owed, so it counts against the net.
    const net = accounts.reduce((s, a) => s + (a.type === 'credit_card' ? -1 : 1) * Number(a.current_balance || 0), 0);
    document.getElementById('netValue').innerHTML = moneyHtml(net);
    document.getElementById('netCard').classList.toggle('hidden', accounts.length === 0);
    if (accounts.length === 0) {
        grid.innerHTML = '<p class="list-empty">No accounts yet. Add one to start uploading statements.</p>';
        return;
    }
    grid.innerHTML = accounts.map(a => {
        const isCard = a.type === 'credit_card';
        const owing = isCard ? a.current_balance > 0 : a.current_balance < 0;
        const meta = [TYPE_LABELS[a.type] || a.type, a.institution].filter(Boolean).map(escapeHtml).join(' · ');
        return `
        <div class="list-row">
            <span class="row-icon" aria-hidden="true"><i class="icon-${TYPE_ICONS[a.type] || 'landmark'}"></i></span>
            <span class="row-main">
                <a href="/accounts/${a._id}" class="row-title">${escapeHtml(a.name)}</a>
                <span class="row-meta">${meta}</span>
            </span>
            <span class="row-end">
                <span class="row-amount ${owing ? 'neg' : ''}">${money(a.current_balance)}</span>
                <span class="row-meta">${isCard ? 'Balance owed' : 'Current balance'}</span>
            </span>
            <span class="row-actions">
                <button type="button" class="icon-btn edit-account" data-id="${a._id}" aria-label="Edit ${escapeHtml(a.name)}"><i class="icon-pencil"></i></button>
                <button type="button" class="icon-btn danger delete-account" data-id="${a._id}" data-name="${escapeHtml(a.name)}" aria-label="Delete ${escapeHtml(a.name)}"><i class="icon-trash-2"></i></button>
            </span>
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

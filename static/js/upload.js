let accounts = [];
const TYPE_LABELS = { chequing: 'Chequing', savings: 'Savings', credit_card: 'Credit card' };

async function loadAccounts() {
    const res = await fetch('/api/accounts');
    const data = await res.json();
    accounts = data.accounts || [];
    const select = document.getElementById('accountSelect');
    select.innerHTML = '<option value="">Select an account&hellip;</option>' +
        accounts.map(a => `<option value="${a._id}">${escapeHtml(a.name)} (${TYPE_LABELS[a.type] || a.type})</option>`).join('');
    document.getElementById('noAccountsHint').classList.toggle('hidden', accounts.length > 0);
}

async function loadStatements() {
    const res = await fetch('/api/statements');
    const data = await res.json();
    const body = document.getElementById('statementsBody');
    const statements = data.statements || [];
    if (statements.length === 0) {
        body.innerHTML = '<tr><td colspan="4" class="muted">No statements yet.</td></tr>';
        return;
    }
    body.innerHTML = statements.map(s => {
        const uploaded = (s.created_at || '').slice(0, 10);
        const statusPill = `<span class="pill">${escapeHtml(s.status)}</span>`;
        const action = s.status === 'failed'
            ? '<span class="muted">Failed &mdash; please re-upload</span>'
            : `<a href="/review/${s._id}" class="link">Review</a>`;
        return `<tr><td class="mono">${uploaded}</td><td>${escapeHtml(s.account_name)}</td><td>${statusPill}</td><td>${action}</td></tr>`;
    }).join('');
}

function escapeHtml(str) {
    const div = document.createElement('div');
    div.textContent = str == null ? '' : String(str);
    return div.innerHTML;
}

document.getElementById('uploadForm').addEventListener('submit', async function (e) {
    e.preventDefault();
    const errEl = document.getElementById('uploadError');
    errEl.classList.add('hidden');

    const accountId = document.getElementById('accountSelect').value;
    const fileInput = document.getElementById('statementFile');
    const file = fileInput.files[0];

    if (!accountId) {
        errEl.textContent = 'Choose an account for this statement.';
        errEl.classList.remove('hidden');
        return;
    }

    if (!file) {
        errEl.textContent = 'Choose a file to upload.';
        errEl.classList.remove('hidden');
        return;
    }
    const allowed = ['.pdf', '.jpg', '.jpeg', '.png'];
    const ext = '.' + file.name.split('.').pop().toLowerCase();
    if (!allowed.includes(ext)) {
        errEl.textContent = 'Unsupported file type. Please upload a PDF, JPG or PNG.';
        errEl.classList.remove('hidden');
        return;
    }
    if (file.size > 10 * 1024 * 1024) {
        errEl.textContent = 'File is too large. The limit is 10 MB.';
        errEl.classList.remove('hidden');
        return;
    }

    document.getElementById('loadingOverlay').classList.remove('hidden');
    try {
        const formData = new FormData();
        formData.append('account_id', accountId);
        formData.append('period_start', document.getElementById('periodStart').value);
        formData.append('period_end', document.getElementById('periodEnd').value);
        formData.append('file', file);

        const res = await fetch('/api/upload', { method: 'POST', body: formData });
        const data = await res.json();
        if (data.error) throw new Error(data.error);
        window.location.href = `/review/${data.statement_id}`;
    } catch (error) {
        errEl.textContent = error.message;
        errEl.classList.remove('hidden');
    } finally {
        document.getElementById('loadingOverlay').classList.add('hidden');
    }
});

loadAccounts();
loadStatements();

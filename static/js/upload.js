let accounts = [];

async function loadAccounts() {
    const res = await fetch('/api/accounts');
    const data = await res.json();
    accounts = data.accounts || [];
    const select = document.getElementById('accountSelect');
    select.innerHTML = '<option value="">Select an account&hellip;</option>' +
        accounts.map(a => `<option value="${a._id}">${escapeHtml(a.name)} (${escapeHtml(a.type)})</option>`).join('');
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

document.getElementById('toggleNewAccount').addEventListener('click', function () {
    const fields = document.getElementById('newAccountFields');
    const select = document.getElementById('accountSelect');
    const show = fields.classList.contains('hidden');
    fields.classList.toggle('hidden', !show);
    this.textContent = show ? '− Use an existing account' : '+ Add a new account';
    if (show) select.value = '';
});

document.getElementById('uploadForm').addEventListener('submit', async function (e) {
    e.preventDefault();
    const errEl = document.getElementById('uploadError');
    errEl.classList.add('hidden');

    let accountId = document.getElementById('accountSelect').value;
    const newName = document.getElementById('newAccountName').value.trim();
    const fileInput = document.getElementById('statementFile');
    const file = fileInput.files[0];

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
        if (!accountId) {
            if (!newName) throw new Error('Choose an account, or enter a name for a new one.');
            const accRes = await fetch('/api/accounts', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ name: newName, type: document.getElementById('newAccountType').value }),
            });
            const accData = await accRes.json();
            if (accData.error) throw new Error(accData.error);
            accountId = accData.account._id;
        }

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

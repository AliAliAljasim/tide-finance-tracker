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
        body.innerHTML = '<p class="list-empty">No statements yet.</p>';
        return;
    }
    const STATUS_LABEL = { processing: 'Processing', parsed: 'Ready to review', confirmed: 'Confirmed', failed: 'Failed' };
    const STATUS_TONE = { processing: '', parsed: 'badge-warning', confirmed: 'badge-positive', failed: 'badge-danger' };
    body.innerHTML = statements.map(s => {
        const uploaded = (s.created_at || '').slice(0, 10);
        const action = s.status === 'failed'
            ? '<span class="row-meta">Please upload it again.</span>'
            : `<a href="/review/${s._id}" class="btn btn-outline btn-sm">Review</a>`;
        return `
        <div class="list-row compact">
            <span class="row-icon" aria-hidden="true"><i class="icon-file-text"></i></span>
            <span class="row-main">
                <span class="row-title">${escapeHtml(s.account_name)}</span>
                <span class="row-meta mono">Uploaded ${uploaded}</span>
            </span>
            <span class="badge badge-dot ${STATUS_TONE[s.status] || ''}">${STATUS_LABEL[s.status] || escapeHtml(s.status)}</span>
            ${action}
        </div>`;
    }).join('');
}

// ── Dropzone ────────────────────────────────────────────────────────────

const dropzone = document.getElementById('dropzone');
const fileInput = document.getElementById('statementFile');

function showChosenFile() {
    const file = fileInput.files[0];
    document.getElementById('dropzoneTitle').textContent = file ? file.name : 'Drop a statement here, or choose a file';
}

fileInput.addEventListener('change', showChosenFile);
dropzone.addEventListener('dragover', e => { e.preventDefault(); dropzone.classList.add('over'); });
dropzone.addEventListener('dragleave', () => dropzone.classList.remove('over'));
dropzone.addEventListener('drop', e => {
    e.preventDefault();
    dropzone.classList.remove('over');
    if (e.dataTransfer.files.length) {
        fileInput.files = e.dataTransfer.files;
        showChosenFile();
    }
});

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

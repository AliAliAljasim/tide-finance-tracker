// Monthly Financial Diary JavaScript

let currentMonth = null;

// Initialize on page load
document.addEventListener('DOMContentLoaded', function() {
    const today = new Date();
    const monthKey = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, '0')}`;
    document.getElementById('monthSelector').value = monthKey;
    currentMonth = monthKey;
    loadMonthData();

    // Drag-and-drop for upload zone
    const zone = document.getElementById('uploadDropZone');
    if (zone) {
        zone.addEventListener('dragover', e => { e.preventDefault(); zone.classList.add('dragover'); });
        zone.addEventListener('dragleave', () => zone.classList.remove('dragover'));
        zone.addEventListener('drop', e => {
            e.preventDefault();
            zone.classList.remove('dragover');
            const file = e.dataTransfer.files[0];
            if (file) setUploadFile(file);
        });
    }
});

// Load transactions and summary for the current month
async function loadMonthData() {
    const monthKey = currentMonth || document.getElementById('monthSelector').value;
    try {
        const resp = await fetch(`/api/transactions/month/${monthKey}`);
        const data = await resp.json();
        const txs = data.transactions || [];

        // Update nav bar stats from transaction data
        let income = 0, expenses = 0;
        txs.forEach(tx => {
            if (tx.type === 'Income') income += tx.amount;
            else expenses += tx.amount;
        });
        const net = income - expenses;
        const fmt = v => '$' + Math.abs(v).toFixed(2);
        document.getElementById('monthIncome').textContent = fmt(income);
        document.getElementById('monthExpenses').textContent = fmt(expenses);
        const netEl = document.getElementById('monthNet');
        netEl.textContent = (net >= 0 ? '+' : '-') + fmt(net);
        netEl.className = 'diary-nav-stat ' + (net >= 0 ? 'income' : 'expense');

        // Render transaction table
        renderTransactions(txs);
    } catch (e) {
        console.error('Error loading month data:', e);
    }
}

function renderTransactions(txs) {
    const empty = document.getElementById('diaryTxEmpty');
    const table = document.getElementById('diaryTxTable');
    const tbody = document.getElementById('diaryTxBody');

    if (!txs.length) {
        empty.style.display = '';
        table.style.display = 'none';
        return;
    }

    empty.style.display = 'none';
    table.style.display = '';
    tbody.innerHTML = '';

    txs.forEach(tx => {
        const isIncome = tx.type === 'Income';
        const dateStr = new Date(tx.date + 'T00:00:00').toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
        const row = document.createElement('tr');
        row.innerHTML = `
            <td class="diary-tx-date">${dateStr}</td>
            <td class="diary-tx-name">${tx.name}</td>
            <td class="diary-tx-cat">${tx.category || '—'}</td>
            <td class="diary-tx-acct">${tx.account || '—'}</td>
            <td class="diary-tx-amount ${isIncome ? 'income' : 'expense'}">${isIncome ? '+' : '-'}$${tx.amount.toFixed(2)}</td>
        `;
        tbody.appendChild(row);
    });
}

function onMonthChange() {
    currentMonth = document.getElementById('monthSelector').value;
    loadMonthData();
}

// Change month using navigation buttons
function changeMonth(delta) {
    const selector = document.getElementById('monthSelector');
    const [year, month] = selector.value.split('-').map(Number);
    const date = new Date(year, month - 1 + delta, 1);
    const newMonthKey = `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}`;
    selector.value = newMonthKey;
    currentMonth = newMonthKey;
    loadMonthData();
}

// Show diary list modal
async function showDiaryList() {
    showLoading(true);

    try {
        const response = await fetch('/api/diary/list');
        const data = await response.json();

        const listContent = document.getElementById('diaryListContent');
        listContent.innerHTML = '';

        if (data.success && data.diaries && data.diaries.length > 0) {
            data.diaries.forEach(diary => {
                const item = document.createElement('div');
                item.className = 'diary-list-item';
                item.onclick = () => loadDiaryFromList(diary.month_key);

                const monthDate = new Date(diary.month_key + '-01');
                const monthName = monthDate.toLocaleDateString('en-US', {
                    year: 'numeric',
                    month: 'long'
                });

                const updated = new Date(diary.updated_at);
                item.innerHTML = `
                    <h3>${monthName}</h3>
                    <p>Last updated: ${updated.toLocaleDateString()}</p>
                `;

                listContent.appendChild(item);
            });
        } else {
            listContent.innerHTML = '<p style="text-align: center; color: var(--text-light);">No diary entries yet.</p>';
        }

        document.getElementById('diaryListModal').classList.add('show');
    } catch (error) {
        console.error('Error loading diary list:', error);
        showNotification('Error loading diary list', 'error');
    } finally {
        showLoading(false);
    }
}

// Load diary from list selection
function loadDiaryFromList(monthKey) {
    document.getElementById('monthSelector').value = monthKey;
    currentMonth = monthKey;
    closeDiaryList();
    loadMonthData();
}

// Close diary list modal
function closeDiaryList() {
    document.getElementById('diaryListModal').classList.remove('show');
}

// Show/hide loading overlay
function showLoading(show) {
    const overlay = document.getElementById('loadingOverlay');
    if (show) {
        overlay.classList.remove('hidden');
    } else {
        overlay.classList.add('hidden');
    }
}

// Show notification
function showNotification(message, type) {
    const notification = document.createElement('div');
    notification.style.cssText = `
        position: fixed;
        top: 20px;
        right: 20px;
        padding: 1rem 2rem;
        background: ${type === 'success' ? '#2ecc71' : '#e74c3c'};
        color: white;
        border-radius: 8px;
        box-shadow: 0 4px 12px rgba(0, 0, 0, 0.2);
        z-index: 3000;
        animation: slideIn 0.3s ease;
    `;
    notification.textContent = message;
    document.body.appendChild(notification);
    setTimeout(() => {
        notification.style.animation = 'slideOut 0.3s ease';
        setTimeout(() => document.body.removeChild(notification), 300);
    }, 3000);
}

// Close modal when clicking outside
window.onclick = function(event) {
    if (event.target === document.getElementById('addTxModal')) closeAddModal();
    if (event.target === document.getElementById('diaryListModal')) closeDiaryList();
    if (event.target === document.getElementById('uploadModal')) closeUploadModal();
    if (event.target === document.getElementById('previewModal')) closePreviewModal();
}

// ===== Add Transaction =====

async function openAddModal() {
    // Pre-fill date to first day of current month
    const monthKey = currentMonth || document.getElementById('monthSelector').value;
    document.getElementById('atDate').value = monthKey + '-01';
    document.getElementById('atName').value = '';
    document.getElementById('atCategory').value = '';
    document.getElementById('atAccount').value = '';
    document.getElementById('atAmount').value = '';
    document.getElementById('atType').value = 'Expense';
    document.getElementById('addTxError').style.display = 'none';

    // Populate datalists
    try {
        const resp = await fetch('/api/form-options');
        const data = await resp.json();
        const catList = document.getElementById('atCategoryList');
        const acctList = document.getElementById('atAccountList');
        catList.innerHTML = (data.categories || []).map(c => `<option value="${c}">`).join('');
        acctList.innerHTML = (data.accounts || []).map(a => `<option value="${a}">`).join('');
    } catch (e) {}

    document.getElementById('addTxModal').classList.add('show');
    setTimeout(() => document.getElementById('atName').focus(), 50);
}

function closeAddModal() {
    document.getElementById('addTxModal').classList.remove('show');
}

async function submitAddTransaction() {
    const errEl = document.getElementById('addTxError');
    const date = document.getElementById('atDate').value;
    const name = document.getElementById('atName').value.trim();
    const amount = parseFloat(document.getElementById('atAmount').value);

    if (!date || !name || isNaN(amount) || amount <= 0) {
        errEl.textContent = 'Please fill in date, description, and a valid amount.';
        errEl.style.display = '';
        return;
    }

    const payload = {
        date,
        name,
        category: document.getElementById('atCategory').value.trim(),
        account: document.getElementById('atAccount').value.trim(),
        type: document.getElementById('atType').value,
        amount
    };

    try {
        const resp = await fetch('/api/add-transaction', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });
        const result = await resp.json();
        if (result.success) {
            closeAddModal();
            // Refresh to the month of the added transaction
            const txMonthKey = date.slice(0, 7);
            document.getElementById('monthSelector').value = txMonthKey;
            currentMonth = txMonthKey;
            await loadMonthData();
            showNotification('Transaction added.', 'success');
        } else {
            errEl.textContent = result.error || 'Failed to add transaction.';
            errEl.style.display = '';
        }
    } catch (e) {
        errEl.textContent = 'Network error. Please try again.';
        errEl.style.display = '';
    }
}

// ===== Statement Upload & Import =====

let parsedStatementData = null;
let selectedFile = null;

function openUploadModal() {
    selectedFile = null;
    document.getElementById('statementFile').value = '';
    document.getElementById('uploadFileName').style.display = 'none';
    document.getElementById('uploadError').style.display = 'none';
    document.getElementById('uploadBtn').disabled = true;
    document.getElementById('uploadModal').classList.add('show');
}

function closeUploadModal() {
    document.getElementById('uploadModal').classList.remove('show');
}

function closePreviewModal() {
    document.getElementById('previewModal').classList.remove('show');
}

function handleFileSelect(event) {
    const file = event.target.files[0];
    setUploadFile(file);
}

function setUploadFile(file) {
    if (!file) return;
    const name = file.name.toLowerCase();
    const errEl = document.getElementById('uploadError');
    if (!name.endsWith('.pdf') && !name.endsWith('.csv')) {
        errEl.textContent = 'Unsupported format. Please upload a PDF or CSV file.';
        errEl.style.display = '';
        document.getElementById('uploadBtn').disabled = true;
        return;
    }
    errEl.style.display = 'none';
    selectedFile = file;
    const nameEl = document.getElementById('uploadFileName');
    nameEl.textContent = `Selected: ${file.name} (${(file.size / 1024).toFixed(1)} KB)`;
    nameEl.style.display = '';
    document.getElementById('uploadBtn').disabled = false;
}

async function parseStatement() {
    if (!selectedFile) return;

    const btn = document.getElementById('uploadBtn');
    const errEl = document.getElementById('uploadError');
    btn.disabled = true;
    btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Analyzing…';
    errEl.style.display = 'none';

    try {
        const formData = new FormData();
        formData.append('file', selectedFile);

        const resp = await fetch('/api/diary/parse-statement', { method: 'POST', body: formData });
        const result = await resp.json();

        if (!result.success) {
            errEl.textContent = result.error || 'Failed to parse statement.';
            errEl.style.display = '';
            return;
        }

        parsedStatementData = result.data;
        closeUploadModal();
        showStatementPreview(result.data);
    } catch (e) {
        errEl.textContent = 'Network error. Please try again.';
        errEl.style.display = '';
    } finally {
        btn.disabled = false;
        btn.innerHTML = '<i class="fas fa-magic"></i> Analyze';
    }
}

function showStatementPreview(data) {
    const txs = data.transactions || [];
    const monthKey = data.month_key || '';

    const monthLabel = monthKey
        ? new Date(monthKey + '-02').toLocaleDateString('en-US', { year: 'numeric', month: 'long' })
        : 'Unknown Month';
    document.getElementById('previewMonthLabel').textContent = monthLabel;

    let totalIncome = 0, totalExpenses = 0;
    txs.forEach(tx => {
        if (tx.type === 'Income') totalIncome += tx.amount;
        else totalExpenses += tx.amount;
    });
    const net = totalIncome - totalExpenses;
    document.getElementById('previewTxCount').textContent = txs.length;
    document.getElementById('previewIncome').textContent = '$' + totalIncome.toFixed(2);
    document.getElementById('previewExpenses').textContent = '$' + totalExpenses.toFixed(2);
    const netEl = document.getElementById('previewNet');
    netEl.textContent = (net >= 0 ? '+' : '') + '$' + Math.abs(net).toFixed(2);
    netEl.className = 'preview-summary-value ' + (net >= 0 ? 'income' : 'expense');

    const tbody = document.getElementById('previewTxBody');
    tbody.innerHTML = '';
    txs.forEach((tx, i) => {
        const row = document.createElement('tr');
        row.innerHTML = `
            <td><input type="checkbox" class="tx-select" data-index="${i}" checked onchange="updateImportCount()"></td>
            <td>${tx.date}</td>
            <td class="tx-desc">${tx.description}</td>
            <td><input class="preview-inline-input" value="${tx.category}" data-index="${i}" data-field="category" onchange="updateTxField(this)"></td>
            <td><input class="preview-inline-input" value="${tx.account}" data-index="${i}" data-field="account" onchange="updateTxField(this)"></td>
            <td><span class="tx-type-badge tx-${tx.type.toLowerCase()}">${tx.type}</span></td>
            <td style="text-align:right;" class="${tx.type === 'Income' ? 'income' : 'expense'}">$${parseFloat(tx.amount).toFixed(2)}</td>
        `;
        tbody.appendChild(row);
    });

    updateImportCount();
    document.getElementById('previewModal').classList.add('show');
}

function toggleSelectAll(checked) {
    document.querySelectorAll('.tx-select').forEach(cb => cb.checked = checked);
    updateImportCount();
}

function updateImportCount() {
    const selected = document.querySelectorAll('.tx-select:checked').length;
    document.getElementById('importCountLabel').textContent = selected;
    const total = document.querySelectorAll('.tx-select').length;
    document.getElementById('selectAllTx').checked = selected === total;
    document.getElementById('selectAllTx').indeterminate = selected > 0 && selected < total;
}

function updateTxField(input) {
    const idx = parseInt(input.dataset.index);
    const field = input.dataset.field;
    if (parsedStatementData && parsedStatementData.transactions[idx]) {
        parsedStatementData.transactions[idx][field] = input.value;
    }
}

async function importStatement() {
    if (!parsedStatementData) return;

    const selectedIndexes = new Set(
        [...document.querySelectorAll('.tx-select:checked')].map(cb => parseInt(cb.dataset.index))
    );

    const transactions = parsedStatementData.transactions.map((tx, i) => ({
        ...tx,
        selected: selectedIndexes.has(i)
    }));

    try {
        const resp = await fetch('/api/diary/import-statement', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ month_key: parsedStatementData.month_key, transactions, diary: {} })
        });
        const result = await resp.json();

        if (result.success) {
            closePreviewModal();
            document.getElementById('monthSelector').value = result.month_key;
            currentMonth = result.month_key;
            await loadMonthData();
            showNotification(`Imported ${result.imported} transactions.`, 'success');
        } else {
            showNotification(result.error || 'Import failed. Please try again.', 'error');
        }
    } catch (e) {
        showNotification('Network error during import.', 'error');
    }
}

// Slide animations
const style = document.createElement('style');
style.textContent = `
    @keyframes slideIn {
        from { transform: translateX(100%); opacity: 0; }
        to { transform: translateX(0); opacity: 1; }
    }
    @keyframes slideOut {
        from { transform: translateX(0); opacity: 1; }
        to { transform: translateX(100%); opacity: 0; }
    }
`;
document.head.appendChild(style);

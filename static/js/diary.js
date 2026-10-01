// Monthly Financial Diary JavaScript

let currentMonth = null;

// Initialize on page load
document.addEventListener('DOMContentLoaded', function() {
    const today = new Date();
    const monthKey = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, '0')}`;
    document.getElementById('monthSelector').value = monthKey;
    currentMonth = monthKey;
    loadMonthData();
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
        netEl.classList.toggle('pos', net >= 0);
        netEl.classList.toggle('neg', net < 0);

        updateHeroSentence(income, net);

        // Render transaction table
        renderTransactions(txs);
    } catch (e) {
        console.error('Error loading month data:', e);
    }
}

// Update the hero sentence with this month's kept-income rate
function updateHeroSentence(income, net) {
    const el = document.getElementById('diaryHeroSentence');
    if (!el) return;

    if (!income) {
        el.textContent = 'No income logged for this month yet.';
        return;
    }

    const keptPct = (net / income) * 100;
    el.innerHTML = `You kept <em>${keptPct.toFixed(1)}%</em> of what came in this month.`;
}

function renderTransactions(txs) {
    const empty = document.getElementById('diaryTxEmpty');
    const table = document.getElementById('diaryTxTable');
    const tbody = document.getElementById('diaryTxBody');

    if (!txs.length) {
        empty.classList.remove('hidden');
        table.classList.add('hidden');
        return;
    }

    empty.classList.add('hidden');
    table.classList.remove('hidden');
    tbody.innerHTML = '';

    txs.forEach(tx => {
        const isIncome = tx.type === 'Income';
        const dateStr = new Date(tx.date + 'T00:00:00').toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
        const row = document.createElement('tr');
        row.innerHTML = `
            <td class="tx-date">${dateStr}</td>
            <td class="tx-name">${tx.name}</td>
            <td class="tx-meta">${tx.category || '—'}</td>
            <td class="tx-meta">${tx.account || '—'}</td>
            <td class="tx-amount ${isIncome ? 'pos' : 'neg'}">${isIncome ? '+' : '-'}$${tx.amount.toFixed(2)}</td>
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
            listContent.innerHTML = '<p class="diary-list-empty">No diary entries yet.</p>';
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
    notification.className = 'toast ' + (type === 'success' ? 'success' : 'error');
    notification.textContent = message;
    document.body.appendChild(notification);
    setTimeout(() => notification.remove(), 3000);
}

// Close modal when clicking outside
window.onclick = function(event) {
    if (event.target === document.getElementById('addTxModal')) closeAddModal();
    if (event.target === document.getElementById('diaryListModal')) closeDiaryList();
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
    document.getElementById('addTxError').classList.add('hidden');

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
        errEl.classList.remove('hidden');
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
            errEl.classList.remove('hidden');
        }
    } catch (e) {
        errEl.textContent = 'Network error. Please try again.';
        errEl.classList.remove('hidden');
    }
}

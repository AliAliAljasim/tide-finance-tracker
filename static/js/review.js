const statementId = document.querySelector('.page').dataset.statementId;
let statement = null;
let categories = [];

function escapeHtml(str) {
    const div = document.createElement('div');
    div.textContent = str == null ? '' : String(str);
    return div.innerHTML;
}

function showToast(message, isError) {
    const toast = document.getElementById('toast');
    toast.textContent = message;
    toast.className = 'toast ' + (isError ? 'error' : 'success');
    setTimeout(() => toast.classList.add('hidden'), 3000);
}

async function load() {
    const res = await fetch(`/api/statements/${statementId}`);
    const data = await res.json();
    if (data.error) {
        document.getElementById('txBody').innerHTML = `<tr><td colspan="7" class="muted">${escapeHtml(data.error)}</td></tr>`;
        return;
    }
    statement = data.statement;
    categories = data.categories || [];
    renderBanner();
    renderRows(data.transactions);
}

function renderBanner() {
    const banner = document.getElementById('statementBanner');
    if (statement.balance_ok === false) {
        banner.textContent = 'Opening balance plus transactions does not match the closing balance on this statement. Check the flagged rows below.';
        banner.classList.remove('hidden');
    } else {
        banner.classList.add('hidden');
    }
}

function renderRows(transactions) {
    const body = document.getElementById('txBody');
    if (transactions.length === 0) {
        body.innerHTML = '<tr><td colspan="7" class="muted">No transactions. Use "Add row" to enter one.</td></tr>';
        return;
    }
    body.innerHTML = transactions.map(rowHtml).join('');
    body.querySelectorAll('tr[data-id]').forEach(attachRowHandlers);
}

function categoryOptions(selectedId) {
    return categories.map(c => `<option value="${c._id}" ${c._id === selectedId ? 'selected' : ''}>${escapeHtml(c.name)}</option>`).join('');
}

function rowHtml(tx) {
    let rowStyle = '';
    let banner = '';
    if (tx.flagged) {
        rowStyle = ' style="background:#FBEAE9;"';
        banner = `<div style="font-size:12px;color:var(--neg);margin-top:4px;">${escapeHtml(tx.flag_reason)}</div>`;
    } else if (tx.is_duplicate) {
        rowStyle = ' style="background:#FDF3DC;"';
        banner = `<div style="font-size:12px;color:#8A6400;margin-top:4px;">Looks like a duplicate of an existing transaction.
            <button type="button" class="link dup-keep" style="background:none;border:0;cursor:pointer;">Keep</button> &middot;
            <button type="button" class="link dup-skip" style="background:none;border:0;cursor:pointer;color:var(--neg);">Skip</button></div>`;
    }
    return `
    <tr data-id="${tx._id}" data-duplicate="${tx.is_duplicate ? 'true' : 'false'}"${rowStyle}>
        <td><input class="input mono" data-field="date" type="date" value="${escapeHtml(tx.date)}"></td>
        <td><input class="input" data-field="description" value="${escapeHtml(tx.description)}">${banner}</td>
        <td><select class="select" data-field="category_id">${categoryOptions(tx.category_id)}</select></td>
        <td class="num"><input class="input mono" data-field="amount" type="number" step="0.01" style="text-align:right;" value="${tx.amount}"></td>
        <td>
            <select class="select" data-field="type">
                <option value="debit" ${tx.type === 'debit' ? 'selected' : ''}>Debit</option>
                <option value="credit" ${tx.type === 'credit' ? 'selected' : ''}>Credit</option>
            </select>
        </td>
        <td class="num"><input class="input mono" data-field="balance" type="number" step="0.01" style="text-align:right;" value="${tx.balance != null ? tx.balance : ''}"></td>
        <td><button type="button" class="btn btn-ghost btn-sm delete-row">Delete</button></td>
    </tr>`;
}

function attachRowHandlers(row) {
    const id = row.dataset.id;

    row.querySelectorAll('[data-field]').forEach(input => {
        input.addEventListener('change', async () => {
            const field = input.dataset.field;
            let value = input.value;
            if (field === 'amount' || field === 'balance') {
                value = input.value === '' ? null : parseFloat(input.value);
            }
            const body = { [field]: value };
            if (field === 'category_id') {
                body.apply_to_all = confirm('Apply this category to all past transactions from this merchant too?');
            }
            await fetch(`/api/statements/${statementId}/transactions/${id}`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(body),
            });
        });
    });

    row.querySelector('.delete-row').addEventListener('click', async () => {
        await fetch(`/api/statements/${statementId}/transactions/${id}`, { method: 'DELETE' });
        row.remove();
    });

    const keepBtn = row.querySelector('.dup-keep');
    if (keepBtn) {
        keepBtn.addEventListener('click', async () => {
            await fetch(`/api/statements/${statementId}/transactions/${id}`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ is_duplicate: false }),
            });
            load();
        });
    }
    const skipBtn = row.querySelector('.dup-skip');
    if (skipBtn) {
        skipBtn.addEventListener('click', async () => {
            await fetch(`/api/statements/${statementId}/transactions/${id}`, { method: 'DELETE' });
            row.remove();
        });
    }
}

document.getElementById('addRowBtn').addEventListener('click', async () => {
    const res = await fetch(`/api/statements/${statementId}/transactions`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ date: new Date().toISOString().slice(0, 10), description: '', amount: 0, type: 'debit' }),
    });
    const data = await res.json();
    const body = document.getElementById('txBody');
    if (body.children.length === 1 && body.children[0].children.length === 1) body.innerHTML = '';
    body.insertAdjacentHTML('beforeend', rowHtml(data.transaction));
    attachRowHandlers(body.lastElementChild);
});

document.getElementById('confirmBtn').addEventListener('click', async () => {
    const unresolved = document.querySelectorAll('#txBody tr[data-duplicate="true"]').length;
    if (unresolved > 0) {
        const ok = confirm(`${unresolved} row(s) still look like duplicates and haven't been resolved. They'll be skipped (not saved) automatically. Continue?`);
        if (!ok) return;
    }
    const res = await fetch(`/api/statements/${statementId}/confirm`, { method: 'POST' });
    const data = await res.json();
    if (data.error) {
        showToast(data.error, true);
        return;
    }
    const note = data.skipped_duplicates ? ` (${data.skipped_duplicates} duplicate row(s) skipped)` : '';
    showToast('Saved. Redirecting to upload...' + note, false);
    setTimeout(() => { window.location.href = '/upload'; }, 1200);
});

document.getElementById('discardBtn').addEventListener('click', async () => {
    if (!confirm('Discard this statement and everything parsed from it?')) return;
    await fetch(`/api/statements/${statementId}`, { method: 'DELETE' });
    window.location.href = '/upload';
});

load();

const accountId = document.querySelector('.page').dataset.accountId;
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

async function load() {
    const res = await fetch(`/api/accounts/${accountId}`);
    const data = await res.json();
    if (data.error) {
        document.getElementById('accountName').textContent = data.error;
        return;
    }
    const a = data.account;
    document.getElementById('accountName').textContent = a.name;
    document.getElementById('accountMeta').textContent =
        `${TYPE_LABELS[a.type] || a.type}${a.institution ? ' · ' + a.institution : ''}`;

    const isCard = a.type === 'credit_card';
    document.getElementById('balanceLabel').textContent = isCard ? 'Balance owed' : 'Current balance';
    const balanceEl = document.getElementById('accountBalance');
    balanceEl.textContent = money(a.current_balance);
    balanceEl.className = 'stat-value ' + ((isCard ? a.current_balance > 0 : a.current_balance < 0) ? 'neg' : 'pos');

    const body = document.getElementById('txBody');
    if (!data.transactions.length) {
        body.innerHTML = '<tr><td colspan="6" class="muted">No confirmed transactions yet. Upload and confirm a statement for this account.</td></tr>';
        return;
    }
    body.innerHTML = data.transactions.map(t => `
        <tr>
            <td class="mono">${escapeHtml(t.date)}</td>
            <td>${escapeHtml(t.description)}</td>
            <td><span class="pill">${escapeHtml(t.category_name)}</span></td>
            <td class="num ${t.type === 'credit' ? 'pos' : ''}">${t.type === 'credit' ? '+' : '-'}${money(t.amount)}</td>
            <td>${t.type === 'credit' ? 'Credit' : 'Debit'}</td>
            <td class="num">${t.balance != null ? money(t.balance) : ''}</td>
        </tr>`).join('');
}

load();

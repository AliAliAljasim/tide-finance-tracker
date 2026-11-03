const accountId = document.querySelector('.page').dataset.accountId;

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

function today() {
    const d = new Date();
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
}

let account = null;

async function load() {
    const res = await fetch(`/api/registered/${accountId}`);
    const data = await res.json();
    if (data.error) {
        document.getElementById('regName').textContent = data.error;
        return;
    }
    account = data.account;
    const cur = account.current;

    document.getElementById('regName').textContent = account.name;
    document.getElementById('regMeta').textContent = [`${account.label} · ${account.type_name}`, account.institution].filter(Boolean).join(' · ');
    document.getElementById('txDate').min = `${account.start_year}-01-01`;
    document.getElementById('txDate').max = today();
    document.getElementById('txTypeIn').textContent = account.kind === 'none' ? 'Deposit' : 'Contribution';

    renderStats(account, cur);
    renderTransactions(data.transactions || []);
    renderYears(account);
    updateRoomHint();
}

function setStat(n, label, valueHtml, sub, negative) {
    document.getElementById(['roomLabel', 'contributedLabel', 'thirdLabel'][n]).textContent = label;
    const v = document.getElementById(['roomValue', 'contributedValue', 'thirdValue'][n]);
    v.innerHTML = valueHtml;
    v.className = 'stat-value' + (negative ? ' neg' : '');
    document.getElementById(['roomSub', 'contributedSub', 'thirdSub'][n]).textContent = sub || '';
}

function showLifetimeBar(contributed, limit, over) {
    const bar = document.getElementById('lifetimeBar');
    bar.classList.remove('hidden');
    bar.firstElementChild.style.width = Math.min(contributed / limit * 100, 100) + '%';
    bar.firstElementChild.className = over ? 'over' : 'quiet';
}

function renderStats(a, cur) {
    const limit = a.lifetime_limit;
    if (a.kind === 'none') {
        setStat(0, 'Net deposited', moneyHtml(cur.total_net), `Since ${a.start_year}`, cur.total_net < 0);
        setStat(1, `Deposited in ${cur.year}`, moneyHtml(cur.contributed), 'No contribution limits on this account');
        setStat(2, `Withdrawn in ${cur.year}`, moneyHtml(cur.withdrawn), '');
        return;
    }
    const over = cur.available < 0;
    if (a.kind === 'lifetime') {
        setStat(0, over ? 'Over the lifetime limit' : 'Lifetime room left', moneyHtml(Math.abs(cur.available)),
            over ? 'Withdraw the excess to stop the penalty tax.' : `${money(cur.lifetime_contributed)} of ${money(limit)} contributed`, over);
        // The lifetime cap is the headline here, so its meter sits under the first card.
        document.getElementById('capBar')?.remove();
        document.getElementById('roomSub').insertAdjacentHTML('afterend',
            `<div class="bar" id="capBar" style="margin-top:12px;"><span class="${over ? 'over' : 'quiet'}" style="width:${Math.min(cur.lifetime_contributed / limit * 100, 100)}%;"></span></div>`);
        setStat(1, `Contributed in ${cur.year}`, moneyHtml(cur.contributed), `Withdrawn: ${money(cur.withdrawn)} (doesn’t restore lifetime room)`);
        if (a.type === 'resp') {
            setStat(2, `Grant earned in ${cur.year}`, moneyHtml(cur.grant_earned), cur.grant_room_left > 0
                ? `Contribute ${money(cur.grant_room_left)} more this year for the full $500 CESG`
                : 'Full $500 CESG for this year');
        } else {
            setStat(2, `Withdrawn in ${cur.year}`, moneyHtml(cur.withdrawn), 'Withdrawals within 10 years of a grant or bond may mean repaying it');
        }
        return;
    }
    setStat(0, over ? `Over-contributed in ${cur.year}` : `Room left in ${cur.year}`, moneyHtml(Math.abs(cur.available)),
        over
            ? (a.type === 'rrsp' ? 'CRA taxes anything beyond a $2,000 cushion at 1%/month.' : 'Withdraw the excess to stop the 1%/month penalty tax.')
            : `${money(cur.room)} of room on Jan 1, ${cur.year}`, over);
    setStat(1, `Contributed in ${cur.year}`, moneyHtml(cur.contributed), '');
    if (a.type === 'fhsa') {
        document.getElementById('contributedSub').textContent = `Withdrawn: ${money(cur.withdrawn)} (FHSA withdrawals don't restore room)`;
        setStat(2, 'Lifetime contributions', moneyHtml(cur.lifetime_contributed), cur.lifetime_remaining >= 0
            ? `${money(cur.lifetime_remaining)} left of the $40,000 limit`
            : `${money(-cur.lifetime_remaining)} over the $40,000 limit`);
        showLifetimeBar(cur.lifetime_contributed, limit, cur.lifetime_remaining < 0);
    } else if (a.type === 'rrsp') {
        setStat(2, `Withdrawn in ${cur.year}`, moneyHtml(cur.withdrawn), a.annual_room > 0
            ? `${money(a.annual_room)} of new room on Jan 1, ${cur.year + 1}. Withdrawals don't restore room.`
            : 'RRSP withdrawals don’t restore room, and tax is withheld');
    } else {
        setStat(2, `Withdrawn in ${cur.year}`, moneyHtml(cur.withdrawn), cur.withdrawn > 0
            ? `Comes back as room on Jan 1, ${cur.year + 1}`
            : 'TFSA withdrawals come back as room the next Jan 1');
    }
}

function renderTransactions(txs) {
    const body = document.getElementById('txBody');
    const inLabel = account.kind === 'none' ? 'Deposit' : 'Contribution';
    if (!txs.length) {
        body.innerHTML = `<tr><td colspan="5" class="muted">No ${inLabel.toLowerCase()}s or withdrawals logged yet.</td></tr>`;
        return;
    }
    body.innerHTML = txs.map(t => `
        <tr>
            <td>${escapeHtml(t.date)}</td>
            <td style="font-weight:600;">${t.type === 'contribution' ? inLabel : 'Withdrawal'}</td>
            <td class="muted">${escapeHtml(t.note || '')}</td>
            <td class="num" style="font-weight:600;">${t.type === 'contribution' ? '+' : '−'}${money(t.amount)}</td>
            <td class="num"><button type="button" class="icon-btn icon-btn-sm danger delete-tx" data-id="${t._id}" aria-label="Delete entry"><i class="icon-trash-2"></i></button></td>
        </tr>`).join('');
    body.querySelectorAll('.delete-tx').forEach(btn => btn.addEventListener('click', () => deleteTransaction(btn.dataset.id)));
}

function renderYears(a) {
    const num = v => `<td class="num">${money(v)}</td>`;
    let head, row;
    if (a.kind === 'none') {
        head = ['Deposited', 'Withdrawn', 'Net', 'Running total'];
        row = y => num(y.contributed) + num(y.withdrawn) + num(y.net) + `<td class="num ${y.total_net < 0 ? 'neg' : ''}">${money(y.total_net)}</td>`;
    } else if (a.kind === 'lifetime') {
        head = ['Room on Jan 1', 'Contributed', 'Withdrawn', 'Lifetime total'].concat(a.type === 'resp' ? ['CESG'] : []);
        row = y => num(y.room) + num(y.contributed) + num(y.withdrawn) + `<td class="num ${y.lifetime_remaining < 0 ? 'neg' : ''}">${money(y.lifetime_contributed)}</td>`
            + (a.type === 'resp' ? num(y.grant_earned) : '');
    } else {
        head = ['Room on Jan 1', 'Contributed', 'Withdrawn', 'Left'].concat(a.type === 'fhsa' ? ['Lifetime total'] : []);
        row = y => num(y.room) + num(y.contributed) + num(y.withdrawn) + `<td class="num ${y.available < 0 ? 'neg' : ''}">${money(y.available)}</td>`
            + (a.type === 'fhsa' ? num(y.lifetime_contributed) : '');
    }
    document.getElementById('yearHead').innerHTML = '<th>Year</th>' + head.map(h => `<th class="num">${h}</th>`).join('');
    document.getElementById('yearBody').innerHTML = a.years.slice().reverse().map(y => `<tr><td>${y.year}</td>${row(y)}</tr>`).join('');
}

// ── Log form ────────────────────────────────────────────────────────────

const txForm = document.getElementById('txForm');
const hint = document.getElementById('txRoomHint');
let pendingPayload = null;

// Live preview of the US-20 check; the server makes the final call.
function updateRoomHint() {
    if (!account) return;
    const type = document.getElementById('txType').value;
    const year = parseInt((document.getElementById('txDate').value || '').slice(0, 4), 10);
    const row = account.years.find(y => y.year === year);
    if (type !== 'contribution' || !row || account.kind === 'none') {
        hint.classList.add('hidden');
        return;
    }
    // A past-year contribution also uses up every later year's room.
    const available = Math.min(...account.years.filter(y => y.year >= year).map(y => y.available));
    const amount = parseFloat(document.getElementById('txAmount').value || '0');
    if (amount > 0 && amount > available + 0.005) {
        hint.textContent = `That's ${money(amount - Math.max(available, 0))} more than your available room (${money(Math.max(available, 0))}).`;
        hint.className = 'callout danger';
    } else {
        hint.textContent = `Available room: ${money(Math.max(available, 0))}`;
        hint.className = 'callout';
    }
}

['txType', 'txDate', 'txAmount'].forEach(id => document.getElementById(id).addEventListener('input', updateRoomHint));

async function saveTransaction(payload) {
    const errEl = document.getElementById('txFormError');
    errEl.classList.add('hidden');
    const res = await fetch(`/api/registered/${accountId}/transactions`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
    });
    const data = await res.json();
    if (data.confirm_required) {
        pendingPayload = payload;
        document.getElementById('overModalText').textContent = data.error;
        overModal.classList.add('show');
        return;
    }
    overModal.classList.remove('show');
    if (data.error) {
        errEl.textContent = data.error;
        errEl.classList.remove('hidden');
        return;
    }
    txForm.reset();
    document.getElementById('txDate').value = today();
    showToast(payload.type === 'contribution' ? 'Contribution saved.' : 'Withdrawal saved.', false);
    load();
}

txForm.addEventListener('submit', function (e) {
    e.preventDefault();
    saveTransaction({
        type: document.getElementById('txType').value,
        date: document.getElementById('txDate').value,
        amount: document.getElementById('txAmount').value,
        note: document.getElementById('txNote').value.trim(),
    });
});

const overModal = document.getElementById('overModal');
document.getElementById('overModalConfirm').addEventListener('click', () => saveTransaction({ ...pendingPayload, force: true }));
document.getElementById('overModalCancel').addEventListener('click', () => overModal.classList.remove('show'));
document.getElementById('overModalClose').addEventListener('click', () => overModal.classList.remove('show'));

async function deleteTransaction(txId) {
    if (!confirm('Delete this entry? Your room will be recalculated.')) return;
    const res = await fetch(`/api/registered/${accountId}/transactions/${txId}`, { method: 'DELETE' });
    const data = await res.json();
    if (data.error) {
        showToast(data.error, true);
        return;
    }
    showToast('Entry deleted.', false);
    load();
}

document.getElementById('deleteRegisteredBtn').addEventListener('click', async () => {
    if (!confirm(`Delete ${account ? account.name : 'this account'} and everything logged for it?`)) return;
    await fetch(`/api/registered/${accountId}`, { method: 'DELETE' });
    location.href = '/investing';
});

document.getElementById('txDate').value = today();
// "Log contribution" / "Log withdrawal" on the list page land here with ?log=<type>.
const requestedLog = new URLSearchParams(location.search).get('log');
if (requestedLog === 'contribution' || requestedLog === 'withdrawal') {
    document.getElementById('txType').value = requestedLog;
    document.getElementById('txAmount').focus();
}
load();

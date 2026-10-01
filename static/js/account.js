// account.js — account detail page logic
// ACCOUNT_TYPE and ACCOUNT_SLUG are injected by the template

const EDIT_SVG = '<svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M11 2.5l2.5 2.5L5.5 13H3v-2.5z"/></svg>';
const DEL_SVG = '<svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M2.5 4.5h11M6 4.5V3h4v1.5M4 4.5l.6 8.5h6.8l.6-8.5"/></svg>';

function fmtCur(v) {
    return new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' }).format(v);
}

function updateTimestamp() {
    const el = document.getElementById('lastUpdate');
    if (el) el.textContent = 'Updated ' + new Date().toLocaleTimeString();
}

// ===== Contribution Banner =====

function renderContribBanner(info) {
    const banner = document.getElementById('contribBanner');
    if (!info) { banner.innerHTML = ''; return; }

    let inner = '';

    const INFO_SVG = '<svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" aria-hidden="true"><circle cx="8" cy="8" r="6.5"/><path d="M8 7.2v4M8 4.9v.1"/></svg>';

    const title = (text, tooltip) => `
        <div class="contrib-title">
            ${text}
            ${tooltip ? `<span class="info-tooltip-wrapper">
                <span class="info-icon">${INFO_SVG}</span>
                <span class="info-tooltip">${tooltip}</span>
            </span>` : ''}
        </div>`;

    const statRow = (stats) => `
        <div class="stat-row">
            ${stats.map(s => `
                <div>
                    <div class="label">${s.label}</div>
                    <div class="stat-value ${s.cls || ''}">${s.value}</div>
                </div>
            `).join('')}
        </div>`;

    const progress = (info, pct) => `
        <div class="contrib-progress">
            <span class="mono">${fmtCur(info.contributed)}</span>
            <div class="bar"><span style="width:${pct}%"></span></div>
            <span class="mono end">${fmtCur(info.lifetimeLimit)}</span>
            <span class="contrib-pct">${pct.toFixed(1)}%</span>
        </div>`;

    if (info.type === 'TFSA' && info.hasTracking) {
        const pct = info.lifetimeLimit > 0
            ? Math.min((info.contributed / info.lifetimeLimit) * 100, 100)
            : 0;
        inner = title(info.description, info.detail) + progress(info, pct);

    } else if (info.type === 'FHSA' && info.needsOpenYear) {
        const currentYear = new Date().getFullYear();
        inner = `
            <div class="contrib-title">
                ${info.description}
                <span class="setup-badge">Setup required</span>
            </div>
            <div class="setup-form">
                <p class="muted">Enter the year you opened your FHSA to enable contribution tracking.</p>
                <div class="setup-row">
                    <input type="number" id="fhsaOpenYearSetup" class="input" min="2023" max="${currentYear}" placeholder="e.g. 2023" aria-label="FHSA open year">
                    <button type="button" onclick="saveFHSAOpenYear()" class="btn btn-primary">Save</button>
                </div>
                <p id="fhsaSetupError" class="form-error" style="display:none"></p>
            </div>`;

    } else if (info.type === 'FHSA' && info.hasTracking) {
        const pct = info.lifetimeLimit > 0
            ? Math.min((info.contributed / info.lifetimeLimit) * 100, 100)
            : 0;
        inner = title(info.description, info.detail) + progress(info, pct);

    } else if (info.type === 'RRSP') {
        inner = `
            <div class="contrib-title">${info.description}</div>
            <div class="contrib-detail">${info.detail}</div>
            ${statRow([
                { label: `${new Date().getFullYear()} Annual Max`, value: fmtCur(info.annualMax) },
                { label: 'Your Room', value: 'See CRA NOA', cls: 'muted' }
            ])}`;

    } else if (info.type === 'RESP') {
        inner = `
            <div class="contrib-title">${info.description}</div>
            <div class="contrib-detail">${info.detail}</div>
            ${statRow([
                { label: 'Lifetime Limit', value: fmtCur(info.lifetimeLimit) },
                { label: 'Optimal Annual (CESG)', value: fmtCur(info.annualCESGOptimal) },
                { label: 'CESG Rate', value: info.cesgRate + '%' },
                { label: 'CESG Lifetime Max', value: fmtCur(info.cesgLifetimeMax) }
            ])}`;

    } else {
        // Non-Registered
        inner = `
            <div class="contrib-title">${info.description}</div>
            <div class="contrib-detail">${info.detail}</div>`;
    }

    banner.innerHTML = inner;
}

// ===== Holdings =====

function renderHoldings(holdings) {
    const tbody = document.getElementById('holdingsBody');
    const statsStrip = document.getElementById('holdingsStatsStrip');

    if (holdings.length === 0) {
        tbody.innerHTML = '<tr><td colspan="10" class="empty-cell">No holdings in this account yet.</td></tr>';
        statsStrip.style.display = 'none';
        return;
    }

    // Compute totals
    let totalMV = 0, totalBV = 0, totalGL = 0;
    holdings.forEach(h => { totalMV += h.marketValue; totalBV += h.bookValue; totalGL += h.gainLoss; });
    const totalReturn = totalBV > 0 ? (totalGL / totalBV) * 100 : 0;

    document.getElementById('acctMarketValue').textContent = fmtCur(totalMV);
    document.getElementById('acctBookValue').textContent = fmtCur(totalBV);

    const glEl = document.getElementById('acctGainLoss');
    glEl.textContent = (totalGL >= 0 ? '+' : '') + fmtCur(totalGL);
    glEl.classList.toggle('pos', totalGL >= 0);
    glEl.classList.toggle('neg', totalGL < 0);

    const retEl = document.getElementById('acctReturn');
    retEl.textContent = (totalReturn >= 0 ? '+' : '') + totalReturn.toFixed(2) + '%';
    retEl.classList.toggle('pos', totalReturn >= 0);
    retEl.classList.toggle('neg', totalReturn < 0);

    statsStrip.style.display = 'flex';

    const iconBtn = (danger, onclick, svg, title) =>
        `<button type="button" onclick="${onclick}" title="${title}" aria-label="${title}" class="icon-btn${danger ? ' danger' : ''}">${svg}</button>`;

    tbody.innerHTML = '';
    holdings.forEach(h => {
        const rPct = h.bookValue > 0 ? (h.gainLoss / h.bookValue) * 100 : 0;
        const glCls = h.gainLoss >= 0 ? 'pos' : 'neg';
        const rCls = rPct >= 0 ? 'pos' : 'neg';
        const safeName = (h.name || '').replace(/'/g, "\\'");

        const tr = document.createElement('tr');
        tr.innerHTML = `
            <td><span class="ticker-symbol">${h.ticker}</span></td>
            <td>${h.name || '-'}</td>
            <td class="num">${h.totalShares}</td>
            <td class="num">${fmtCur(h.avgCost)}</td>
            <td class="num">${fmtCur(h.price)}</td>
            <td class="num tx-strong">${fmtCur(h.marketValue)}</td>
            <td class="num">${fmtCur(h.bookValue)}</td>
            <td class="num ${glCls}">${fmtCur(h.gainLoss)}</td>
            <td class="num"><span class="return-pill ${rCls}">${rPct >= 0 ? '+' : ''}${rPct.toFixed(2)}%</span></td>
            <td class="actions">
                ${iconBtn(false, `openEditHolding('${h.id}', '${h.ticker}', '${safeName}', ${h.totalShares}, ${h.avgCost})`, EDIT_SVG, 'Edit')}
                ${iconBtn(true, `openDeleteHolding('${h.id}', '${h.ticker}')`, DEL_SVG, 'Delete')}
            </td>`;
        tbody.appendChild(tr);
    });
}

// ===== Deposits (TFSA only) =====

async function loadDeposits() {
    const tbody = document.getElementById('depositsBody');
    if (!tbody) return;
    try {
        const resp = await fetch('/api/tfsa-deposits');
        const data = await resp.json();
        if (data.error) throw new Error(data.error);
        tbody.innerHTML = '';
        if (data.deposits.length === 0) {
            tbody.innerHTML = '<tr><td colspan="4" class="empty-cell">No deposits yet</td></tr>';
            return;
        }
        data.deposits.forEach(d => {
            const safeNote = (d.note || '').replace(/'/g, "\\'");
            const tr = document.createElement('tr');
            tr.innerHTML = `
                <td class="tx-muted mono">${d.date}</td>
                <td class="num tx-strong">${fmtCur(d.amount)}</td>
                <td class="tx-muted">${d.note || '-'}</td>
                <td class="actions">
                    <button type="button" onclick="openEditDeposit(${d.row}, '${d.date}', ${d.amount}, '${safeNote}')" title="Edit" aria-label="Edit" class="icon-btn">${EDIT_SVG}</button>
                    <button type="button" onclick="openDeleteItem('deposit', ${d.row}, '${fmtCur(d.amount)} deposit on ${d.date}')" title="Delete" aria-label="Delete" class="icon-btn danger">${DEL_SVG}</button>
                </td>`;
            tbody.appendChild(tr);
        });
    } catch (err) {
        console.error('Error loading deposits:', err);
    }
}

// ===== FHSA Open Year Setup =====

async function saveFHSAOpenYear() {
    const input = document.getElementById('fhsaOpenYearSetup');
    const errEl = document.getElementById('fhsaSetupError');
    const year = parseInt(input.value, 10);
    const currentYear = new Date().getFullYear();

    if (!year || year < 2023 || year > currentYear) {
        errEl.textContent = `Please enter a year between 2023 and ${currentYear}.`;
        errEl.style.display = '';
        return;
    }
    errEl.style.display = 'none';

    try {
        const resp = await fetch('/api/settings/update', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ fhsaOpenYear: year })
        });
        const data = await resp.json();
        if (data.success) {
            refreshData();
        } else {
            errEl.textContent = 'Failed to save. Please try again.';
            errEl.style.display = '';
        }
    } catch (e) {
        errEl.textContent = 'Network error. Please try again.';
        errEl.style.display = '';
    }
}

// ===== FHSA Deposits =====

async function loadFHSADeposits() {
    const tbody = document.getElementById('fhsaDepositsBody');
    if (!tbody) return;
    try {
        const resp = await fetch('/api/fhsa-deposits');
        const data = await resp.json();
        if (data.error) throw new Error(data.error);
        tbody.innerHTML = '';
        if (data.deposits.length === 0) {
            tbody.innerHTML = '<tr><td colspan="4" class="empty-cell">No deposits yet</td></tr>';
            return;
        }
        data.deposits.forEach(d => {
            const safeNote = (d.note || '').replace(/'/g, "\\'");
            const tr = document.createElement('tr');
            tr.innerHTML = `
                <td class="tx-muted mono">${d.date}</td>
                <td class="num tx-strong">${fmtCur(d.amount)}</td>
                <td class="tx-muted">${d.note || '-'}</td>
                <td class="actions">
                    <button type="button" onclick="openEditFHSADeposit(${d.row}, '${d.date}', ${d.amount}, '${safeNote}')" title="Edit" aria-label="Edit" class="icon-btn">${EDIT_SVG}</button>
                    <button type="button" onclick="openDeleteItem('fhsa-deposit', ${d.row}, '${fmtCur(d.amount)} deposit on ${d.date}')" title="Delete" aria-label="Delete" class="icon-btn danger">${DEL_SVG}</button>
                </td>`;
            tbody.appendChild(tr);
        });
    } catch (err) {
        console.error('Error loading FHSA deposits:', err);
    }
}

function showFHSADepositModal() {
    document.getElementById('fhsaDepositModal').classList.add('show');
    document.getElementById('fhsaDepositDate').valueAsDate = new Date();
}
function closeFHSADepositModal() {
    document.getElementById('fhsaDepositModal').classList.remove('show');
    document.getElementById('fhsaDepositForm').reset();
}
function openEditFHSADeposit(id, date, amount, note) {
    document.getElementById('editFHSADepositId').value = id;
    document.getElementById('editFHSADepositDate').value = date;
    document.getElementById('editFHSADepositAmount').value = amount;
    document.getElementById('editFHSADepositNote').value = note;
    document.getElementById('editFHSADepositModal').classList.add('show');
}
function closeEditFHSADepositModal() {
    document.getElementById('editFHSADepositModal').classList.remove('show');
}

// ===== Trades (TFSA only) =====

function updateTradeTotalCost() {
    const shares = parseFloat(document.getElementById('tradeShares').value) || 0;
    const cost   = parseFloat(document.getElementById('tradeCost').value)   || 0;
    const fees   = parseFloat(document.getElementById('tradeFees').value)   || 0;
    document.getElementById('totalCost').textContent = fmtCur((shares * cost) + fees);
}

async function loadTrades() {
    const tbody = document.getElementById('tradesBody');
    if (!tbody) return;
    try {
        const resp = await fetch('/api/tfsa-trades');
        const data = await resp.json();
        if (data.error) throw new Error(data.error);
        tbody.innerHTML = '';
        if (data.trades.length === 0) {
            tbody.innerHTML = '<tr><td colspan="7" class="empty-cell">No trades yet</td></tr>';
            return;
        }
        data.trades.forEach(t => {
            const tr = document.createElement('tr');
            tr.innerHTML = `
                <td class="tx-muted mono">${t.date}</td>
                <td><span class="ticker-symbol">${t.ticker}</span></td>
                <td class="num">${t.shares}</td>
                <td class="num">${fmtCur(t.costPerShare)}</td>
                <td class="num">${fmtCur(t.fees)}</td>
                <td class="num tx-strong">${fmtCur(t.totalCost)}</td>
                <td class="actions">
                    <button type="button" onclick="openEditTrade(${t.row}, '${t.date}', '${t.ticker}', ${t.shares}, ${t.costPerShare}, ${t.fees})" title="Edit" aria-label="Edit" class="icon-btn">${EDIT_SVG}</button>
                    <button type="button" onclick="openDeleteItem('trade', ${t.row}, '${t.ticker} trade on ${t.date}')" title="Delete" aria-label="Delete" class="icon-btn danger">${DEL_SVG}</button>
                </td>`;
            tbody.appendChild(tr);
        });
    } catch (err) {
        console.error('Error loading trades:', err);
    }
}

// ===== Deposit modal helpers =====

function showDepositModal() {
    document.getElementById('depositModal').classList.add('show');
    document.getElementById('depositDate').valueAsDate = new Date();
}
function closeDepositModal() {
    document.getElementById('depositModal').classList.remove('show');
    document.getElementById('depositForm').reset();
}
function openEditDeposit(id, date, amount, note) {
    document.getElementById('editDepositId').value = id;
    document.getElementById('editDepositDate').value = date;
    document.getElementById('editDepositAmount').value = amount;
    document.getElementById('editDepositNote').value = note;
    document.getElementById('editDepositModal').classList.add('show');
}
function closeEditDepositModal() {
    document.getElementById('editDepositModal').classList.remove('show');
}

// ===== Trade modal helpers =====

function showTradeModal() {
    document.getElementById('tradeModal').classList.add('show');
    document.getElementById('tradeDate').valueAsDate = new Date();
}
function closeTradeModal() {
    document.getElementById('tradeModal').classList.remove('show');
    document.getElementById('tradeForm').reset();
    document.getElementById('totalCost').textContent = '$0.00';
    document.getElementById('tradeTickerSymbol').value = '';
    document.getElementById('tradeTickerDropdown').innerHTML = '';
    document.getElementById('tradeTickerDropdown').classList.remove('show');
}
function openEditTrade(id, date, ticker, shares, costPerShare, fees) {
    document.getElementById('editTradeId').value = id;
    document.getElementById('editTradeDate').value = date;
    document.getElementById('editTradeTicker').value = ticker;
    document.getElementById('editTradeShares').value = shares;
    document.getElementById('editTradeCost').value = costPerShare;
    document.getElementById('editTradeFees').value = fees;
    document.getElementById('editTradeModal').classList.add('show');
}
function closeEditTradeModal() {
    document.getElementById('editTradeModal').classList.remove('show');
}

// ===== Data Load =====

async function refreshData() {
    document.getElementById('loadingOverlay').classList.remove('hidden');
    try {
        const resp = await fetch(`/api/account-detail/${ACCOUNT_SLUG}`);
        const data = await resp.json();
        if (data.error) throw new Error(data.error);
        renderContribBanner(data.contributionInfo);
        renderHoldings(data.holdings);
        if (ACCOUNT_TYPE === 'TFSA') {
            await Promise.all([loadDeposits(), loadTrades()]);
        }
        if (ACCOUNT_TYPE === 'FHSA') {
            await loadFHSADeposits();
        }
        updateTimestamp();
    } catch (err) {
        console.error('Error loading account data:', err);
    } finally {
        document.getElementById('loadingOverlay').classList.add('hidden');
    }
}

async function forceRefreshPrices() {
    document.getElementById('loadingOverlay').classList.remove('hidden');
    try {
        await fetch('/api/refresh-prices', { method: 'POST' });
        await refreshData();
    } catch (err) {
        console.error('Error refreshing prices:', err);
    } finally {
        document.getElementById('loadingOverlay').classList.add('hidden');
    }
}

// ===== Add Holding Modal =====

function showAddHoldingModal() {
    document.getElementById('addHoldingModal').classList.add('show');
}

function closeAddHoldingModal() {
    document.getElementById('addHoldingModal').classList.remove('show');
    document.getElementById('addHoldingForm').reset();
    document.getElementById('holdingTickerSymbol').value = '';
    document.getElementById('holdingTickerDropdown').innerHTML = '';
    document.getElementById('holdingTickerDropdown').classList.remove('show');
}

// ===== Edit Holding =====

function openEditHolding(id, ticker, name, shares, avgCost) {
    document.getElementById('editHoldingId').value = id;
    document.getElementById('editHoldingTicker').value = ticker;
    document.getElementById('editHoldingTickerInput').value = ticker;
    document.getElementById('editHoldingName').value = name;
    document.getElementById('editHoldingShares').value = shares;
    document.getElementById('editHoldingAvgCost').value = avgCost;
    document.getElementById('editHoldingModal').classList.add('show');
}

function closeEditHoldingModal() {
    document.getElementById('editHoldingModal').classList.remove('show');
    document.getElementById('editHoldingTickerDropdown').innerHTML = '';
    document.getElementById('editHoldingTickerDropdown').classList.remove('show');
}

// ===== Delete (holdings, deposits, trades) =====

var pendingDelete = null;

function openDeleteHolding(id, ticker) {
    openDeleteItem('holding', id, ticker);
}

function openDeleteItem(type, id, description) {
    pendingDelete = { type, id };
    document.getElementById('deleteConfirmMessage').textContent = `Delete ${description}?`;
    document.getElementById('deleteConfirmModal').classList.add('show');
}

function closeDeleteModal() {
    document.getElementById('deleteConfirmModal').classList.remove('show');
    pendingDelete = null;
}

async function executeDelete() {
    if (!pendingDelete) return;
    const { type, id } = pendingDelete;
    closeDeleteModal();
    const urlMap = {
        holding:       `/api/delete-holding/${id}`,
        deposit:       `/api/delete-tfsa-deposit/${id}`,
        trade:         `/api/delete-tfsa-trade/${id}`,
        'fhsa-deposit': `/api/delete-fhsa-deposit/${id}`,
        account:       `/api/delete-account/${id}`,
    };
    document.getElementById('loadingOverlay').classList.remove('hidden');
    try {
        const resp = await fetch(urlMap[type], { method: 'DELETE' });
        const result = await resp.json();
        if (result.error) throw new Error(result.error);
        if (type === 'account') {
            window.location.href = '/stocks';
        } else {
            await refreshData();
        }
    } catch (err) {
        alert('Failed to delete: ' + err.message);
    } finally {
        document.getElementById('loadingOverlay').classList.add('hidden');
    }
}

function confirmDeleteAccount() {
    pendingDelete = { type: 'account', id: ACCOUNT_TYPE };
    document.getElementById('deleteConfirmMessage').textContent =
        `Close ${ACCOUNT_TYPE} account? This will permanently delete all holdings in this account.`;
    document.getElementById('deleteConfirmModal').classList.add('show');
}

// ===== DOMContentLoaded =====

document.addEventListener('DOMContentLoaded', function () {
    // Add holding form
    document.getElementById('addHoldingForm').addEventListener('submit', async function (e) {
        e.preventDefault();
        const ticker = document.getElementById('holdingTickerSymbol').value;
        if (!ticker) { alert('Please select a valid ticker from the dropdown'); return; }

        document.getElementById('loadingOverlay').classList.remove('hidden');
        try {
            const resp = await fetch('/api/add-holding', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    ticker,
                    accountType: ACCOUNT_TYPE,
                    name: document.getElementById('holdingName').value,
                    shares: parseFloat(document.getElementById('holdingShares').value),
                    avgCost: parseFloat(document.getElementById('holdingAvgCost').value),
                })
            });
            const result = await resp.json();
            if (result.error) throw new Error(result.error);
            closeAddHoldingModal();
            await refreshData();
        } catch (err) {
            alert('Failed to add holding: ' + err.message);
        } finally {
            document.getElementById('loadingOverlay').classList.add('hidden');
        }
    });

    // Edit holding form
    document.getElementById('editHoldingForm').addEventListener('submit', async function (e) {
        e.preventDefault();
        const id = document.getElementById('editHoldingId').value;
        document.getElementById('loadingOverlay').classList.remove('hidden');
        try {
            const resp = await fetch(`/api/update-holding/${id}`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    ticker: document.getElementById('editHoldingTicker').value,
                    accountType: ACCOUNT_TYPE,
                    name: document.getElementById('editHoldingName').value,
                    shares: parseFloat(document.getElementById('editHoldingShares').value),
                    avgCost: parseFloat(document.getElementById('editHoldingAvgCost').value),
                })
            });
            const result = await resp.json();
            if (result.error) throw new Error(result.error);
            closeEditHoldingModal();
            await refreshData();
        } catch (err) {
            alert('Failed to update holding: ' + err.message);
        } finally {
            document.getElementById('loadingOverlay').classList.add('hidden');
        }
    });

    // Delete confirm button
    document.getElementById('confirmDeleteBtn').addEventListener('click', executeDelete);

    // FHSA-only: deposit forms
    if (ACCOUNT_TYPE === 'FHSA') {
        document.getElementById('fhsaDepositForm').addEventListener('submit', async function (e) {
            e.preventDefault();
            document.getElementById('loadingOverlay').classList.remove('hidden');
            try {
                const resp = await fetch('/api/add-fhsa-deposit', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        date: document.getElementById('fhsaDepositDate').value,
                        amount: parseFloat(document.getElementById('fhsaDepositAmount').value),
                        note: document.getElementById('fhsaDepositNote').value
                    })
                });
                const result = await resp.json();
                if (result.error) throw new Error(result.error);
                closeFHSADepositModal();
                await refreshData();
            } catch (err) {
                alert('Failed to add deposit: ' + err.message);
            } finally {
                document.getElementById('loadingOverlay').classList.add('hidden');
            }
        });

        document.getElementById('editFHSADepositForm').addEventListener('submit', async function (e) {
            e.preventDefault();
            const id = document.getElementById('editFHSADepositId').value;
            document.getElementById('loadingOverlay').classList.remove('hidden');
            try {
                const resp = await fetch(`/api/update-fhsa-deposit/${id}`, {
                    method: 'PUT',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        date: document.getElementById('editFHSADepositDate').value,
                        amount: parseFloat(document.getElementById('editFHSADepositAmount').value),
                        note: document.getElementById('editFHSADepositNote').value
                    })
                });
                const result = await resp.json();
                if (result.error) throw new Error(result.error);
                closeEditFHSADepositModal();
                await refreshData();
            } catch (err) {
                alert('Failed to update deposit: ' + err.message);
            } finally {
                document.getElementById('loadingOverlay').classList.add('hidden');
            }
        });
    }

    // TFSA-only: deposit and trade forms
    if (ACCOUNT_TYPE === 'TFSA') {
        document.getElementById('depositForm').addEventListener('submit', async function (e) {
            e.preventDefault();
            document.getElementById('loadingOverlay').classList.remove('hidden');
            try {
                const resp = await fetch('/api/add-tfsa-deposit', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        date: document.getElementById('depositDate').value,
                        amount: parseFloat(document.getElementById('depositAmount').value),
                        note: document.getElementById('depositNote').value
                    })
                });
                const result = await resp.json();
                if (result.error) throw new Error(result.error);
                closeDepositModal();
                await refreshData();
            } catch (err) {
                alert('Failed to add deposit: ' + err.message);
            } finally {
                document.getElementById('loadingOverlay').classList.add('hidden');
            }
        });

        document.getElementById('editDepositForm').addEventListener('submit', async function (e) {
            e.preventDefault();
            const id = document.getElementById('editDepositId').value;
            document.getElementById('loadingOverlay').classList.remove('hidden');
            try {
                const resp = await fetch(`/api/update-tfsa-deposit/${id}`, {
                    method: 'PUT',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        date: document.getElementById('editDepositDate').value,
                        amount: parseFloat(document.getElementById('editDepositAmount').value),
                        note: document.getElementById('editDepositNote').value
                    })
                });
                const result = await resp.json();
                if (result.error) throw new Error(result.error);
                closeEditDepositModal();
                await refreshData();
            } catch (err) {
                alert('Failed to update deposit: ' + err.message);
            } finally {
                document.getElementById('loadingOverlay').classList.add('hidden');
            }
        });

        document.getElementById('tradeForm').addEventListener('submit', async function (e) {
            e.preventDefault();
            const ticker = document.getElementById('tradeTickerSymbol').value;
            if (!ticker) { alert('Please select a valid ticker from the dropdown'); return; }
            document.getElementById('loadingOverlay').classList.remove('hidden');
            try {
                const resp = await fetch('/api/add-tfsa-trade', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        date: document.getElementById('tradeDate').value,
                        ticker,
                        accountType: 'TFSA',
                        shares: parseFloat(document.getElementById('tradeShares').value),
                        costPerShare: parseFloat(document.getElementById('tradeCost').value),
                        fees: parseFloat(document.getElementById('tradeFees').value) || 0
                    })
                });
                const result = await resp.json();
                if (result.error) throw new Error(result.error);
                closeTradeModal();
                await refreshData();
            } catch (err) {
                alert('Failed to add trade: ' + err.message);
            } finally {
                document.getElementById('loadingOverlay').classList.add('hidden');
            }
        });

        document.getElementById('editTradeForm').addEventListener('submit', async function (e) {
            e.preventDefault();
            const id = document.getElementById('editTradeId').value;
            document.getElementById('loadingOverlay').classList.remove('hidden');
            try {
                const resp = await fetch(`/api/update-tfsa-trade/${id}`, {
                    method: 'PUT',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        date: document.getElementById('editTradeDate').value,
                        ticker: document.getElementById('editTradeTicker').value,
                        shares: parseFloat(document.getElementById('editTradeShares').value),
                        costPerShare: parseFloat(document.getElementById('editTradeCost').value),
                        fees: parseFloat(document.getElementById('editTradeFees').value) || 0
                    })
                });
                const result = await resp.json();
                if (result.error) throw new Error(result.error);
                closeEditTradeModal();
                await refreshData();
            } catch (err) {
                alert('Failed to update trade: ' + err.message);
            } finally {
                document.getElementById('loadingOverlay').classList.add('hidden');
            }
        });

        ['tradeShares', 'tradeCost', 'tradeFees'].forEach(id => {
            document.getElementById(id).addEventListener('input', updateTradeTotalCost);
        });

        initializeTickerAutocomplete('tradeTicker', 'tradeTickerDropdown', 'tradeTickerSymbol');
    }

    // Close modals on outside click
    window.addEventListener('click', function (e) {
        const allModals = ['addHoldingModal', 'editHoldingModal', 'deleteConfirmModal',
                           'depositModal', 'editDepositModal', 'tradeModal', 'editTradeModal',
                           'fhsaDepositModal', 'editFHSADepositModal'];
        allModals.forEach(id => {
            const modal = document.getElementById(id);
            if (modal && e.target === modal) modal.classList.remove('show');
        });
    });

    // Ticker autocomplete (reuses function from stocks.js)
    initializeTickerAutocomplete('holdingTicker', 'holdingTickerDropdown', 'holdingTickerSymbol', 'holdingName');
    initializeTickerAutocomplete('editHoldingTickerInput', 'editHoldingTickerDropdown', 'editHoldingTicker', 'editHoldingName');

    refreshData();
    setInterval(refreshData, 5 * 60 * 1000);
});

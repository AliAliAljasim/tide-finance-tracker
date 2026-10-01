// Named categories get a fixed, stable color (identity, not rank) — anything
// else (Health, Subscriptions, Fees & interest, Other, ...) folds into a
// single gray "Other" bucket rather than generating more hues past the
// validated 8-slot categorical palette. See the dataviz skill's palette.md.
const CATEGORY_COLOR_ORDER = ['Groceries', 'Dining', 'Rent / Mortgage', 'Utilities', 'Transportation', 'Shopping', 'Entertainment'];
const CATEGORY_COLORS = ['var(--cat-1)', 'var(--cat-2)', 'var(--cat-3)', 'var(--cat-4)', 'var(--cat-5)', 'var(--cat-6)', 'var(--cat-7)'];

function escapeHtml(str) {
    const div = document.createElement('div');
    div.textContent = str == null ? '' : String(str);
    return div.innerHTML;
}
function money(n) {
    const v = Number(n || 0);
    return (v < 0 ? '-$' : '$') + Math.abs(v).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}
function compactMoney(n) {
    const v = Number(n || 0);
    const abs = Math.abs(v);
    const sign = v < 0 ? '-' : '';
    if (abs >= 1000) return sign + '$' + (abs / 1000).toFixed(1).replace(/\.0$/, '') + 'K';
    return sign + '$' + Math.round(abs);
}
function niceStep(maxValue) {
    if (maxValue <= 0) return 100;
    const raw = maxValue / 4;
    const mag = Math.pow(10, Math.floor(Math.log10(raw)));
    const norm = raw / mag;
    const step = norm < 1.5 ? 1 : norm < 3.5 ? 2.5 : norm < 7.5 ? 5 : 10;
    return step * mag;
}
function monthLabel(ym) {
    const [y, m] = ym.split('-').map(Number);
    return new Date(y, m - 1, 1).toLocaleDateString(undefined, { month: 'short', year: '2-digit' });
}
function thisMonth() {
    const d = new Date();
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`;
}
function monthsAgo(n) {
    const d = new Date();
    d.setMonth(d.getMonth() - n);
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`;
}

const tooltip = document.getElementById('vizTooltip');
function showTooltip(evt, html) {
    tooltip.innerHTML = html;
    tooltip.style.left = evt.clientX + 'px';
    tooltip.style.top = evt.clientY + 'px';
    tooltip.style.display = 'block';
}
function hideTooltip() { tooltip.style.display = 'none'; }

// ── Accounts filter ─────────────────────────────────────────────────────

async function loadAccountFilter() {
    const res = await fetch('/api/accounts');
    const data = await res.json();
    const select = document.getElementById('accountFilter');
    const labels = { chequing: 'Chequing', savings: 'Savings', credit_card: 'Credit card' };
    (data.accounts || []).forEach(a => {
        const opt = document.createElement('option');
        opt.value = a._id;
        opt.textContent = `${a.name} (${labels[a.type] || a.type})`;
        select.appendChild(opt);
    });
}

function currentAccount() { return document.getElementById('accountFilter').value; }

// ── Stat cards ──────────────────────────────────────────────────────────

async function loadStatCards() {
    const m = thisMonth();
    const res = await fetch(`/api/summary/monthly?from=${m}&to=${m}&account=${currentAccount()}`);
    const data = await res.json();
    const row = (data.months || [])[0] || { income: 0, expenses: 0, net: 0 };
    document.getElementById('cardIncome').textContent = money(row.income);
    document.getElementById('cardExpenses').textContent = money(row.expenses);
    const netEl = document.getElementById('cardNet');
    netEl.textContent = money(row.net);
    netEl.className = 'stat-value ' + (row.net >= 0 ? 'pos' : 'neg');
}

// ── Monthly income vs. expenses (grouped bar) ──────────────────────────

async function loadMonthlyChart() {
    const from = document.getElementById('monthlyFrom').value;
    const to = document.getElementById('monthlyTo').value;
    const res = await fetch(`/api/summary/monthly?from=${from}&to=${to}&account=${currentAccount()}`);
    const data = await res.json();
    renderMonthlyChart(data.months || []);
    renderMonthlyTable(data.months || []);
}

function renderMonthlyTable(months) {
    document.getElementById('monthlyTableBody').innerHTML = months.map(m => `
        <tr><td>${monthLabel(m.month)}</td><td class="num">${money(m.income)}</td><td class="num">${money(m.expenses)}</td><td class="num">${money(m.net)}</td></tr>
    `).join('') || '<tr><td colspan="4" class="muted">No data.</td></tr>';
}

function renderMonthlyChart(months) {
    const container = document.getElementById('monthlyChart');
    if (!months.length) {
        container.innerHTML = '<p class="muted">No data for this range.</p>';
        return;
    }
    const width = Math.max(container.clientWidth || 640, 320);
    const height = 240, padTop = 24, padBottom = 32, padLeft = 44, padRight = 12;
    const plotW = width - padLeft - padRight, plotH = height - padTop - padBottom;

    const maxVal = Math.max(1, ...months.map(m => Math.max(m.income, m.expenses)));
    const step = niceStep(maxVal);
    const axisMax = Math.ceil(maxVal / step) * step + step;
    const y = v => padTop + plotH - (v / axisMax) * plotH;

    const groupW = plotW / months.length;
    const barW = Math.min(24, groupW * 0.32);
    const gap = 2;

    let gridlines = '';
    let ticks = Math.round(axisMax / step);
    for (let i = 0; i <= ticks; i++) {
        const val = i * step;
        const yy = y(val);
        gridlines += `<line x1="${padLeft}" x2="${width - padRight}" y1="${yy}" y2="${yy}" stroke="var(--grid-line)" stroke-width="1"/>`;
        gridlines += `<text x="${padLeft - 8}" y="${yy + 4}" text-anchor="end" font-size="11" fill="var(--text-muted)">${compactMoney(val)}</text>`;
    }

    let bars = '';
    months.forEach((m, i) => {
        const cx = padLeft + groupW * i + groupW / 2;
        const incH = plotH - (y(m.income) - padTop);
        const expH = plotH - (y(m.expenses) - padTop);
        const incX = cx - barW - gap / 2;
        const expX = cx + gap / 2;
        bars += bar(incX, y(m.income), barW, incH, 'var(--series-income)', `inc-${i}`);
        bars += bar(expX, y(m.expenses), barW, expH, 'var(--series-expense)', `exp-${i}`);
        if (m.income > 0) bars += label(incX + barW / 2, y(m.income) - 6, compactMoney(m.income));
        if (m.expenses > 0) bars += label(expX + barW / 2, y(m.expenses) - 6, compactMoney(m.expenses));
        bars += `<text x="${cx}" y="${height - padBottom + 18}" text-anchor="middle" font-size="12" fill="var(--text-secondary)">${monthLabel(m.month)}</text>`;
        bars += `<rect class="viz-bar" data-tip="inc-${i}" x="${incX}" y="${padTop}" width="${barW}" height="${plotH}" fill="transparent"/>`;
        bars += `<rect class="viz-bar" data-tip="exp-${i}" x="${expX}" y="${padTop}" width="${barW}" height="${plotH}" fill="transparent"/>`;
    });

    container.innerHTML = `<svg width="${width}" height="${height}" viewBox="0 0 ${width} ${height}">
        ${gridlines}
        <line x1="${padLeft}" x2="${width - padRight}" y1="${padTop + plotH}" y2="${padTop + plotH}" stroke="var(--axis-line)" stroke-width="1"/>
        ${bars}
    </svg>`;

    const tips = {};
    months.forEach((m, i) => { tips[`inc-${i}`] = `${monthLabel(m.month)} &middot; Income ${money(m.income)}`; tips[`exp-${i}`] = `${monthLabel(m.month)} &middot; Expenses ${money(m.expenses)}`; });
    container.querySelectorAll('[data-tip]').forEach(el => {
        el.addEventListener('mousemove', evt => showTooltip(evt, tips[el.dataset.tip]));
        el.addEventListener('mouseleave', hideTooltip);
    });
}

function bar(x, y, w, h, fill, key) {
    const r = Math.min(4, w / 2, Math.max(h, 0.01) / 2);
    h = Math.max(h, 0);
    if (h < r) return `<rect x="${x}" y="${y}" width="${w}" height="${h}" fill="${fill}"/>`;
    return `<path d="M${x},${y + h} V${y + r} Q${x},${y} ${x + r},${y} H${x + w - r} Q${x + w},${y} ${x + w},${y + r} V${y + h} Z" fill="${fill}"/>`;
}
function label(cx, y, text) {
    return `<text x="${cx}" y="${y}" text-anchor="middle" font-size="11" fill="var(--text-secondary)" font-variant-numeric="tabular-nums">${text}</text>`;
}

// ── Spending by category (sorted single-series bar) ─────────────────────

let lastCategoryRows = [];

async function loadCategoryChart() {
    const month = document.getElementById('categoryMonth').value;
    const res = await fetch(`/api/summary/categories?month=${month}&account=${currentAccount()}`);
    const data = await res.json();
    const rows = foldCategories(data.categories || []);
    lastCategoryRows = rows;
    renderCategoryChart(rows, month);
    renderCategoryTable(rows);
    document.getElementById('categoryDrilldown').classList.add('hidden');
}

function foldCategories(rows) {
    const named = [];
    let otherTotal = 0;
    const otherBreakdown = [];
    rows.forEach(r => {
        if (CATEGORY_COLOR_ORDER.includes(r.category)) {
            named.push(r);
        } else {
            otherTotal += r.total;
            otherBreakdown.push(r);
        }
    });
    const result = named.slice();
    if (otherTotal > 0) {
        result.push({ category: 'Other', category_id: null, total: otherTotal, breakdown: otherBreakdown });
    }
    result.sort((a, b) => b.total - a.total);
    return result;
}

function colorFor(categoryName) {
    const idx = CATEGORY_COLOR_ORDER.indexOf(categoryName);
    return idx >= 0 ? CATEGORY_COLORS[idx] : 'var(--cat-other)';
}

function renderCategoryTable(rows) {
    document.getElementById('categoryTableBody').innerHTML = rows.map(r => `
        <tr><td><span class="viz-swatch" style="background:${colorFor(r.category)};"></span>${escapeHtml(r.category)}</td><td class="num">${money(r.total)}</td></tr>
    `).join('') || '<tr><td colspan="2" class="muted">No spending this month.</td></tr>';
}

function renderCategoryChart(rows, month) {
    const container = document.getElementById('categoryChart');
    if (!rows.length) {
        container.innerHTML = '<p class="muted">No spending for this month.</p>';
        return;
    }
    const width = Math.max(container.clientWidth || 640, 280);
    const narrow = width < 420;
    const rowH = 36, padLeft = narrow ? 86 : 150, padRight = narrow ? 44 : 70, padTop = 8;
    const height = padTop + rows.length * rowH;
    const plotW = width - padLeft - padRight;
    const maxVal = Math.max(1, ...rows.map(r => r.total));

    let bars = '';
    rows.forEach((r, i) => {
        const y0 = padTop + i * rowH + 6;
        const h = rowH - 12;
        const w = Math.max(2, (r.total / maxVal) * plotW);
        const clickable = r.category_id ? 'clickable' : '';
        bars += `<text x="${padLeft - 10}" y="${y0 + h / 2 + 4}" text-anchor="end" font-size="13" fill="var(--text-secondary)">${escapeHtml(r.category)}</text>`;
        bars += `<g class="viz-bar ${clickable}" data-idx="${i}">`;
        bars += bar(padLeft, y0, w, h, colorFor(r.category), `cat-${i}`);
        bars += `<rect x="${padLeft}" y="${y0}" width="${Math.max(w, 40)}" height="${h}" fill="transparent"/>`;
        bars += `</g>`;
        bars += `<text x="${padLeft + w + 8}" y="${y0 + h / 2 + 4}" font-size="12" fill="var(--text-secondary)" font-variant-numeric="tabular-nums">${compactMoney(r.total)}</text>`;
    });

    container.innerHTML = `<svg width="${width}" height="${height}" viewBox="0 0 ${width} ${height}">${bars}</svg>`;

    container.querySelectorAll('[data-idx]').forEach(el => {
        const row = rows[Number(el.dataset.idx)];
        el.addEventListener('mousemove', evt => {
            const tip = row.category_id
                ? `${escapeHtml(row.category)} &middot; ${money(row.total)}`
                : `${escapeHtml(row.category)} &middot; ${money(row.total)}<br>${(row.breakdown || []).map(b => `${escapeHtml(b.category)}: ${money(b.total)}`).join('<br>')}`;
            showTooltip(evt, tip);
        });
        el.addEventListener('mouseleave', hideTooltip);
        if (row.category_id) {
            el.addEventListener('click', () => loadDrilldown(row, month));
        }
    });
}

async function loadDrilldown(row, month) {
    const res = await fetch(`/api/summary/categories/transactions?month=${month}&category_id=${row.category_id}&account=${currentAccount()}`);
    const data = await res.json();
    document.getElementById('drilldownTitle').textContent = `${row.category} — ${monthLabel(month)}`;
    document.getElementById('drilldownBody').innerHTML = (data.transactions || []).map(t => `
        <tr><td class="mono">${escapeHtml(t.date)}</td><td>${escapeHtml(t.description)}</td><td class="num">${money(t.amount)}</td></tr>
    `).join('') || '<tr><td colspan="3" class="muted">No transactions.</td></tr>';
    document.getElementById('categoryDrilldown').classList.remove('hidden');
}

// ── Table-view toggles ──────────────────────────────────────────────────

function wireToggle(buttonId, chartId, tableId) {
    const btn = document.getElementById(buttonId);
    btn.addEventListener('click', () => {
        const showingTable = document.getElementById(tableId).classList.toggle('show');
        document.getElementById(chartId).classList.toggle('hidden', showingTable);
        btn.textContent = showingTable ? 'Chart view' : 'Table view';
    });
}
wireToggle('monthlyTableToggle', 'monthlyChart', 'monthlyTable');
wireToggle('categoryTableToggle', 'categoryChart', 'categoryTable');

// ── Wire up filters & boot ───────────────────────────────────────────────

document.getElementById('monthlyFrom').value = monthsAgo(5);
document.getElementById('monthlyTo').value = thisMonth();
document.getElementById('categoryMonth').value = thisMonth();

document.getElementById('accountFilter').addEventListener('change', () => { loadStatCards(); loadMonthlyChart(); loadCategoryChart(); });
document.getElementById('monthlyFrom').addEventListener('change', loadMonthlyChart);
document.getElementById('monthlyTo').addEventListener('change', loadMonthlyChart);
document.getElementById('categoryMonth').addEventListener('change', loadCategoryChart);
window.addEventListener('resize', () => { loadMonthlyChart(); loadCategoryChart(); });

(async function init() {
    await loadAccountFilter();
    loadStatCards();
    loadMonthlyChart();
    loadCategoryChart();
})();

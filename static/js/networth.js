let networthChart = null;
let fullHistory    = [];
let activeRange    = 'ALL';
let goals = [];
let selectedIcon = 'fa-bullseye';
let selectedColor = '#2F4BFF';
let currentGoalType = 'target';

const ICONS = [
    { icon: 'fa-bullseye',       label: 'Goal'      },
    { icon: 'fa-home',           label: 'Home'      },
    { icon: 'fa-car',            label: 'Car'       },
    { icon: 'fa-plane',          label: 'Travel'    },
    { icon: 'fa-graduation-cap', label: 'Education' },
    { icon: 'fa-piggy-bank',     label: 'Savings'   },
    { icon: 'fa-heart',          label: 'Health'    },
    { icon: 'fa-shield-alt',     label: 'Emergency' },
    { icon: 'fa-chart-line',     label: 'Invest'    },
    { icon: 'fa-ring',           label: 'Wedding'   },
    { icon: 'fa-baby',           label: 'Family'    },
    { icon: 'fa-laptop',         label: 'Tech'      },
];

const COLORS = [
    '#2F4BFF',
    '#1F7A4D',
    '#0F766E',
    '#7C3AED',
    '#C2410C',
    '#B4432F',
    '#BE185D',
    '#666A72',
];

const ICON_PATHS = {
    'fa-bullseye': '<circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="5"/><circle cx="12" cy="12" r="1.5"/>',
    'fa-home': '<path d="M3 11l9-8 9 8"/><path d="M5 10v10h14V10"/>',
    'fa-car': '<path d="M5 16v-5l2-5h10l2 5v5"/><path d="M3 16h18"/><circle cx="7.5" cy="18" r="1.5"/><circle cx="16.5" cy="18" r="1.5"/>',
    'fa-plane': '<path d="M22 2L11 13"/><path d="M22 2l-7 20-4-9-9-4 20-7z"/>',
    'fa-graduation-cap': '<path d="M2 9l10-5 10 5-10 5-10-5z"/><path d="M6 11.5V16c0 1.5 3 3 6 3s6-1.5 6-3v-4.5"/>',
    'fa-piggy-bank': '<circle cx="12" cy="12" r="9"/><path d="M12 7v10"/><path d="M14.5 9.5c0-1-1-1.5-2.5-1.5s-2.5.7-2.5 1.7 1 1.4 2.5 1.8 2.5.8 2.5 1.8-1 1.7-2.5 1.7-2.5-.5-2.5-1.5"/>',
    'fa-heart': '<path d="M12 20s-8-5-8-11a4.5 4.5 0 0 1 8-2.5A4.5 4.5 0 0 1 20 9c0 6-8 11-8 11z"/>',
    'fa-shield-alt': '<path d="M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6l8-3z"/>',
    'fa-chart-line': '<path d="M3 3v18h18"/><path d="M7 15l4-4 3 3 5-6"/>',
    'fa-ring': '<circle cx="12" cy="15" r="6"/><path d="M9 6l3-3 3 3-3 3z"/>',
    'fa-baby': '<circle cx="12" cy="12" r="9"/><circle cx="9" cy="10.5" r=".8"/><circle cx="15" cy="10.5" r=".8"/><path d="M9 15c1 1 5 1 6 0"/>',
    'fa-laptop': '<rect x="4" y="5" width="16" height="11" rx="1"/><path d="M2 19h20"/>',
    pen: '<path d="M4 20h4L19 9l-4-4L4 16v4z"/>',
    trash: '<path d="M4 7h16"/><path d="M9 7V4h6v3"/><path d="M6 7l1 13h10l1-13"/>',
    calendar: '<rect x="4" y="5" width="16" height="15" rx="2"/><path d="M4 10h16M9 3v4M15 3v4"/>',
    check: '<path d="M5 12l5 5 9-10"/>',
    flame: '<path d="M12 3c1 4 5 5 5 10a5 5 0 0 1-10 0c0-2 1-3 2-4 0 2 1 3 2 3 0-3-1-6 1-9z"/>',
    circle: '<circle cx="12" cy="12" r="8"/>',
};

function svgIcon(name, size = 18) {
    const paths = ICON_PATHS[name] || ICON_PATHS['fa-bullseye'];
    return `<svg viewBox="0 0 24 24" width="${size}" height="${size}" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${paths}</svg>`;
}

// ── Formatters ──────────────────────────────────────────────────────

function formatCurrency(amount) {
    return new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' }).format(amount);
}

function formatShortCurrency(amount) {
    if (Math.abs(amount) >= 1000000) return '$' + (amount / 1000000).toFixed(1) + 'M';
    if (Math.abs(amount) >= 1000)    return '$' + (amount / 1000).toFixed(1) + 'k';
    return formatCurrency(amount);
}

function formatDate(dateStr) {
    const d = new Date(dateStr.length === 10 ? dateStr + 'T00:00:00' : dateStr);
    return d.toLocaleDateString('en-US', { month: 'short', year: 'numeric' });
}

function capitalize(str) {
    return str.charAt(0).toUpperCase() + str.slice(1);
}

function escapeHtml(str) {
    return str
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;');
}

function hexToRgba(hex, alpha) {
    const r = parseInt(hex.slice(1, 3), 16);
    const g = parseInt(hex.slice(3, 5), 16);
    const b = parseInt(hex.slice(5, 7), 16);
    return `rgba(${r},${g},${b},${alpha})`;
}

// ── Init ────────────────────────────────────────────────────────────

async function init() {
    buildIconPicker();
    buildColorPicker();
    await Promise.all([loadNetworthData(), loadGoals()]);
    autoSnapshot();
}

async function autoSnapshot() {
    const today = new Date().toISOString().slice(0, 10);
    const lastSnap = localStorage.getItem('lastSnapDate');
    const lastVer  = localStorage.getItem('snapVer');
    if (lastSnap === today && lastVer === '2') return;
    try {
        const res = await fetch('/api/create-networth-snapshot', { method: 'POST' });
        const data = await res.json();
        if (!data.error) {
            localStorage.setItem('lastSnapDate', today);
            localStorage.setItem('snapVer', '2');
            await loadNetworthData();
        }
    } catch (_) {}
}

// ── Data Loading ─────────────────────────────────────────────────────

async function loadNetworthData() {
    try {
        const [dashRes, histRes] = await Promise.all([
            fetch('/api/dashboard-data'),
            fetch('/api/networth-history'),
        ]);
        const dashData = await dashRes.json();
        const histData = await histRes.json();

        if (!dashData.error) {
            updateHero(dashData.accounts, histData.history || []);
            updateBreakdown(dashData.accounts);
        }
        if (!histData.error) {
            fullHistory = histData.history || [];
            renderChart(filterHistory(fullHistory, activeRange));
        }
    } catch (e) {
        console.error('Error loading net worth data:', e);
    }
}

async function loadGoals() {
    try {
        const res  = await fetch('/api/goals');
        const data = await res.json();
        if (!data.error) {
            goals = data;
            renderGoals(goals);
        }
    } catch (e) {
        console.error('Error loading goals:', e);
    }
}

// ── Hero ─────────────────────────────────────────────────────────────

function updateHero(accounts, history) {
    const total = (accounts.chequing || 0) + (accounts.cash || 0) + (accounts.tfsa || 0);
    document.getElementById('heroNetWorth').textContent = formatCurrency(total);

    if (history.length >= 2) {
        const prev   = history[history.length - 2].total;
        const change = total - prev;
        const pct    = prev > 0 ? ((change / prev) * 100).toFixed(1) : 0;
        const sign   = change >= 0 ? '+' : '';
        const el     = document.getElementById('heroNetWorthChange');
        el.textContent = `${sign}${formatCurrency(change)} (${sign}${pct}%) vs last snapshot`;
        el.className = 'stat-sub ' + (change >= 0 ? 'pos' : 'neg');
    }
}

// ── Breakdown Cards ──────────────────────────────────────────────────

function updateBreakdown(accounts) {
    document.getElementById('valChequing').textContent = formatCurrency(accounts.chequing || 0);
    document.getElementById('valCash').textContent     = formatCurrency(accounts.cash     || 0);
    document.getElementById('valTFSA').textContent     = formatCurrency(accounts.tfsa     || 0);
}

// ── Range Filter ─────────────────────────────────────────────────────

function filterHistory(history, range) {
    if (range === 'ALL' || !history.length) return history;
    const months = { '1M': 1, '3M': 3, '6M': 6, '1Y': 12 }[range] || 999;
    const cutoff = new Date();
    cutoff.setMonth(cutoff.getMonth() - months);
    const cutoffKey = cutoff.toISOString().slice(0, 7); // YYYY-MM
    return history.filter(h => h.monthKey >= cutoffKey);
}

function setRange(range) {
    activeRange = range;
    document.querySelectorAll('.nw-range-btn').forEach(b =>
        b.classList.toggle('active', b.dataset.range === range)
    );
    renderChart(filterHistory(fullHistory, range));
}

// ── Chart ─────────────────────────────────────────────────────────────

function renderChart(history) {
    const canvas  = document.getElementById('networthChart');
    const emptyEl = document.getElementById('chartEmpty');

    if (history.length === 0) {
        emptyEl.classList.remove('hidden');
        canvas.style.display = 'none';
        return;
    }

    emptyEl.classList.add('hidden');
    canvas.style.display = '';

    if (networthChart) networthChart.destroy();

    const ctx2d    = canvas.getContext('2d');
    const h        = canvas.offsetHeight || 300;
    const gradient = ctx2d.createLinearGradient(0, 0, 0, h);
    gradient.addColorStop(0,   'rgba(47,75,255,0.18)');
    gradient.addColorStop(0.6, 'rgba(47,75,255,0.05)');
    gradient.addColorStop(1,   'rgba(47,75,255,0)');
    Chart.defaults.font.family = "'DM Sans', system-ui, sans-serif";

    const labels = history.map(s => s.monthKey);

    networthChart = new Chart(canvas, {
        type: 'line',
        data: {
            labels,
            datasets: [
                {
                    label: 'Net Worth',
                    data: history.map(s => s.total),
                    borderColor: '#2F4BFF',
                    backgroundColor: gradient,
                    borderWidth: 2,
                    tension: 0.4,
                    fill: true,
                    pointRadius: 0,
                    pointHoverRadius: 5,
                    pointHoverBackgroundColor: '#2F4BFF',
                    pointHoverBorderColor: 'white',
                    pointHoverBorderWidth: 2,
                },
            ],
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            interaction: { mode: 'index', intersect: false },
            layout: { padding: { left: 0, right: 0, bottom: 0 } },
            plugins: {
                legend: { display: false },
                tooltip: {
                    backgroundColor: '#16181D',
                    titleColor: 'rgba(255,255,255,0.65)',
                    bodyColor: '#FFFFFF',
                    padding: { top: 10, bottom: 10, left: 14, right: 14 },
                    cornerRadius: 8,
                    titleFont: { size: 11 },
                    bodyFont: { size: 13, weight: '700' },
                    callbacks: {
                        title: items => items[0].label,
                        label: c => `  ${formatCurrency(c.parsed.y)}`,
                    },
                },
            },
            scales: {
                y: {
                    beginAtZero: false,
                    border: { display: false },
                    ticks: {
                        maxTicksLimit: 4,
                        callback: v => formatShortCurrency(v),
                        color: '#666A72',
                        font: { size: 11, family: "'DM Mono', monospace" },
                        padding: 10,
                    },
                    grid: { color: '#E6E1D6', drawTicks: false },
                },
                x: {
                    display: false,
                    grid: { display: false },
                },
            },
        },
    });
}

// ── Goals Rendering ──────────────────────────────────────────────────

function renderGoals(goalsArr) {
    const grid    = document.getElementById('goalsGrid');
    const emptyEl = document.getElementById('goalsEmpty');

    if (!goalsArr.length) {
        grid.innerHTML = '';
        emptyEl.classList.remove('hidden');
        return;
    }

    emptyEl.classList.add('hidden');
    grid.innerHTML = goalsArr.map(renderGoalCard).join('');
}

function renderGoalCard(goal) {
    const color = goal.color || '#2F4BFF';
    const icon  = goal.icon  || 'fa-bullseye';
    return goal.goalType === 'periodic'
        ? renderPeriodicCard(goal, color, icon)
        : renderTargetCard(goal, color, icon);
}

function goalActionsHtml(goal) {
    return `<div class="goal-actions">
        <button class="icon-btn" onclick="editGoal(${goal.id})" title="Edit" aria-label="Edit goal">${svgIcon('pen', 15)}</button>
        <button class="icon-btn" onclick="deleteGoalConfirm(${goal.id})" title="Delete" aria-label="Delete goal">${svgIcon('trash', 15)}</button>
    </div>`;
}

function renderTargetCard(goal, color, icon) {
    const pct = goal.targetAmount > 0
        ? Math.min((goal.currentAmount / goal.targetAmount) * 100, 100).toFixed(1)
        : 0;

    const deadlineHtml = goal.deadline
        ? `<span class="goal-meta">${svgIcon('calendar', 13)} ${formatDate(goal.deadline)}</span>`
        : '';

    const contribHtml = goal.monthlyContribution > 0
        ? `<span class="chip">${formatCurrency(goal.monthlyContribution)}/mo</span>`
        : '';

    const remaining = Math.max(0, goal.targetAmount - goal.currentAmount);
    const etaHtml = (goal.monthlyContribution > 0 && remaining > 0)
        ? `<span class="chip">${Math.ceil(remaining / goal.monthlyContribution)} mo to go</span>`
        : '';

    return `
    <div class="card goal-card" data-id="${goal.id}">
        <div class="goal-head">
            <div class="goal-icon" style="background:${hexToRgba(color, 0.12)};color:${color}">${svgIcon(icon, 20)}</div>
            <div class="goal-info">
                <h3 class="goal-title">${escapeHtml(goal.title)}</h3>
                ${deadlineHtml}
            </div>
            ${goalActionsHtml(goal)}
        </div>
        <div class="goal-amounts">
            <span style="color:${color}">${formatCurrency(goal.currentAmount)}</span>
            <span class="sep"> / </span>
            <span class="of">${formatCurrency(goal.targetAmount)}</span>
        </div>
        <div class="goal-bar"><span style="width:${pct}%;background:${color}"></span></div>
        <div class="goal-foot">
            <span class="pct">${pct}% complete</span>
            <div class="goal-chips">${contribHtml}${etaHtml}</div>
        </div>
    </div>`;
}

function renderPeriodicCard(goal, color, icon) {
    const freqLabels = {
        weekly: 'week', biweekly: '2 wks', monthly: 'month',
        quarterly: 'quarter', yearly: 'year',
    };
    const freqLabel = freqLabels[goal.contributionFrequency] || 'period';
    const streak    = goal.streakCount || 0;

    const streakHtml = streak > 0
        ? `<span class="goal-streak on">${svgIcon('flame', 18)} ${streak} streak</span>`
        : `<span class="goal-streak off">${svgIcon('circle', 18)} Start your streak</span>`;

    const lastCheckin = goal.lastCheckIn
        ? `<span class="goal-meta">Last: ${formatDate(goal.lastCheckIn)}</span>`
        : '<span></span>';

    return `
    <div class="card goal-card" data-id="${goal.id}">
        <div class="goal-head">
            <div class="goal-icon" style="background:${hexToRgba(color, 0.12)};color:${color}">${svgIcon(icon, 20)}</div>
            <div class="goal-info">
                <h3 class="goal-title">${escapeHtml(goal.title)}</h3>
                <span class="goal-freq">${capitalize(goal.contributionFrequency || 'Monthly')}</span>
            </div>
            ${goalActionsHtml(goal)}
        </div>
        <div class="goal-foot">
            ${streakHtml}
            <span class="goal-contrib">${formatCurrency(goal.monthlyContribution)}<small>/${freqLabel}</small></span>
        </div>
        <div class="goal-foot">
            ${lastCheckin}
            <button class="checkin-btn" onclick="checkInGoal(${goal.id})" style="background:${color}">${svgIcon('check', 15)} Check in</button>
        </div>
    </div>`;
}

// ── Goal CRUD ─────────────────────────────────────────────────────────

function openGoalModal(goalData = null) {
    document.getElementById('goalId').value             = goalData ? goalData.id : '';
    document.getElementById('goalModalTitle').textContent = goalData ? 'Edit Goal' : 'Add Goal';
    document.getElementById('goalTitle').value          = goalData ? goalData.title : '';
    document.getElementById('goalTargetAmount').value   = goalData ? goalData.targetAmount  : '';
    document.getElementById('goalCurrentAmount').value  = goalData ? goalData.currentAmount : '';
    document.getElementById('goalMonthlyContrib').value = goalData ? goalData.monthlyContribution : '';
    document.getElementById('goalDeadline').value       = goalData && goalData.deadline ? goalData.deadline : '';
    document.getElementById('goalPeriodicAmount').value = goalData ? goalData.monthlyContribution : '';
    document.getElementById('goalFrequency').value      = goalData && goalData.contributionFrequency
        ? goalData.contributionFrequency : 'monthly';

    selectedIcon  = goalData ? (goalData.icon  || 'fa-bullseye') : 'fa-bullseye';
    selectedColor = goalData ? (goalData.color || '#2F4BFF')     : '#2F4BFF';

    setGoalType(goalData ? (goalData.goalType || 'target') : 'target');
    refreshIconPicker();
    refreshColorPicker();

    document.getElementById('goalModal').classList.add('show');
}

function closeGoalModal() {
    document.getElementById('goalModal').classList.remove('show');
}

function handleModalOverlayClick(e) {
    if (e.target === document.getElementById('goalModal')) {
        closeGoalModal();
    }
}

function setGoalType(type) {
    currentGoalType = type;
    document.getElementById('typeTarget').classList.toggle('active', type === 'target');
    document.getElementById('typePeriodic').classList.toggle('active', type === 'periodic');
    document.getElementById('targetFields').style.display   = type === 'target'   ? '' : 'none';
    document.getElementById('periodicFields').style.display = type === 'periodic' ? '' : 'none';
}

async function saveGoal() {
    const id    = document.getElementById('goalId').value;
    const title = document.getElementById('goalTitle').value.trim();
    if (!title) { alert('Please enter a title.'); return; }

    const payload = {
        title,
        icon:  selectedIcon,
        color: selectedColor,
        goalType: currentGoalType,
        targetAmount: currentGoalType === 'target'
            ? parseFloat(document.getElementById('goalTargetAmount').value  || 0) : 0,
        currentAmount: currentGoalType === 'target'
            ? parseFloat(document.getElementById('goalCurrentAmount').value || 0) : 0,
        monthlyContribution: currentGoalType === 'target'
            ? parseFloat(document.getElementById('goalMonthlyContrib').value   || 0)
            : parseFloat(document.getElementById('goalPeriodicAmount').value   || 0),
        deadline: currentGoalType === 'target'
            ? (document.getElementById('goalDeadline').value || null) : null,
        contributionFrequency: currentGoalType === 'periodic'
            ? document.getElementById('goalFrequency').value : null,
    };

    try {
        const url    = id ? `/api/goals/${id}` : '/api/goals';
        const method = id ? 'PUT' : 'POST';
        const res  = await fetch(url, {
            method,
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
        });
        const data = await res.json();
        if (data.error) throw new Error(data.error);
        closeGoalModal();
        await loadGoals();
    } catch (e) {
        alert('Failed to save goal: ' + e.message);
    }
}

function editGoal(id) {
    const goal = goals.find(g => g.id === id);
    if (goal) openGoalModal(goal);
}

function deleteGoalConfirm(id) {
    if (!confirm('Delete this goal?')) return;
    deleteGoal(id);
}

async function deleteGoal(id) {
    try {
        const res  = await fetch(`/api/goals/${id}`, { method: 'DELETE' });
        const data = await res.json();
        if (data.error) throw new Error(data.error);
        await loadGoals();
    } catch (e) {
        alert('Failed to delete goal: ' + e.message);
    }
}

async function checkInGoal(id) {
    try {
        const res  = await fetch(`/api/goals/${id}/checkin`, { method: 'POST' });
        const data = await res.json();
        if (data.error) throw new Error(data.error);
        if (data.alreadyDone) {
            alert("You've already checked in today!");
            return;
        }
        await loadGoals();
    } catch (e) {
        alert('Failed to check in: ' + e.message);
    }
}


// ── Icon / Color Pickers ─────────────────────────────────────────────

function buildIconPicker() {
    const el = document.getElementById('iconPicker');
    el.innerHTML = ICONS.map(({ icon, label }) =>
        `<button type="button" class="icon-pick-btn" data-icon="${icon}" title="${label}" aria-label="${label}" onclick="selectIcon('${icon}')">${svgIcon(icon, 18)}</button>`
    ).join('');
}

function buildColorPicker() {
    const el = document.getElementById('colorPicker');
    el.innerHTML = COLORS.map(color =>
        `<button type="button" class="color-pick-btn" data-color="${color}" aria-label="Color ${color}" onclick="selectColor('${color}')" style="background:${color}"></button>`
    ).join('');
}

function refreshIconPicker() {
    document.querySelectorAll('.icon-pick-btn').forEach(btn => {
        btn.classList.toggle('selected', btn.dataset.icon === selectedIcon);
    });
}

function refreshColorPicker() {
    document.querySelectorAll('.color-pick-btn').forEach(btn => {
        btn.classList.toggle('selected', btn.dataset.color === selectedColor);
    });
}

function selectIcon(icon) {
    selectedIcon = icon;
    refreshIconPicker();
}

function selectColor(color) {
    selectedColor = color;
    refreshColorPicker();
}

// ── Boot ──────────────────────────────────────────────────────────────

document.addEventListener('DOMContentLoaded', init);

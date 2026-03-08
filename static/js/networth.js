let networthChart = null;
let fullHistory    = [];
let activeRange    = 'ALL';
let goals = [];
let selectedIcon = 'fa-bullseye';
let selectedColor = '#0FB9A8';
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
    '#0FB9A8',
    '#22C55E',
    '#3B82F6',
    '#8B5CF6',
    '#F59E0B',
    '#EF4444',
    '#EC4899',
    '#64748B',
];

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
        el.className   = 'nw-hero-change ' + (change >= 0 ? 'nw-hero-up' : 'nw-hero-down');
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
    gradient.addColorStop(0,   'rgba(15,185,168,0.35)');
    gradient.addColorStop(0.6, 'rgba(15,185,168,0.08)');
    gradient.addColorStop(1,   'rgba(15,185,168,0)');

    const labels = history.map(s => s.monthKey);

    networthChart = new Chart(canvas, {
        type: 'line',
        data: {
            labels,
            datasets: [
                {
                    label: 'Net Worth',
                    data: history.map(s => s.total),
                    borderColor: '#0FB9A8',
                    backgroundColor: gradient,
                    borderWidth: 2,
                    tension: 0.4,
                    fill: true,
                    pointRadius: 0,
                    pointHoverRadius: 5,
                    pointHoverBackgroundColor: '#0FB9A8',
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
                    backgroundColor: 'rgba(15,23,42,0.9)',
                    titleColor: 'rgba(255,255,255,0.5)',
                    bodyColor: '#0FB9A8',
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
                        color: '#444448',
                        font: { size: 10 },
                        padding: 10,
                    },
                    grid: { color: 'rgba(255,255,255,0.04)', drawTicks: false },
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
    const color = goal.color || '#0FB9A8';
    const icon  = goal.icon  || 'fa-bullseye';
    return goal.goalType === 'periodic'
        ? renderPeriodicCard(goal, color, icon)
        : renderTargetCard(goal, color, icon);
}

function renderTargetCard(goal, color, icon) {
    const pct = goal.targetAmount > 0
        ? Math.min((goal.currentAmount / goal.targetAmount) * 100, 100).toFixed(1)
        : 0;

    const deadlineHtml = goal.deadline
        ? `<span class="goal-deadline"><i class="fas fa-calendar-alt"></i> ${formatDate(goal.deadline)}</span>`
        : '';

    const contribHtml = goal.monthlyContribution > 0
        ? `<span class="goal-contrib">${formatCurrency(goal.monthlyContribution)}/mo</span>`
        : '';

    const remaining = Math.max(0, goal.targetAmount - goal.currentAmount);
    const etaHtml = (goal.monthlyContribution > 0 && remaining > 0)
        ? `<span class="goal-eta">${Math.ceil(remaining / goal.monthlyContribution)} mo to go</span>`
        : '';

    return `
    <div class="goal-card" data-id="${goal.id}">
        <div class="goal-card-top">
            <div class="goal-icon-wrap" style="background:${hexToRgba(color, 0.12)};color:${color}">
                <i class="fas ${icon}"></i>
            </div>
            <div class="goal-title-area">
                <h3 class="goal-title">${escapeHtml(goal.title)}</h3>
                ${deadlineHtml}
            </div>
            <div class="goal-card-actions">
                <button class="goal-action-btn" onclick="editGoal(${goal.id})" title="Edit">
                    <i class="fas fa-pen"></i>
                </button>
                <button class="goal-action-btn goal-action-delete" onclick="deleteGoalConfirm(${goal.id})" title="Delete">
                    <i class="fas fa-trash"></i>
                </button>
            </div>
        </div>
        <div class="goal-amounts">
            <span class="goal-current" style="color:${color}">${formatCurrency(goal.currentAmount)}</span>
            <span class="goal-sep"> / </span>
            <span class="goal-target-val">${formatCurrency(goal.targetAmount)}</span>
        </div>
        <div class="goal-progress-bar">
            <div class="goal-progress-fill" style="width:${pct}%;background:${color}"></div>
        </div>
        <div class="goal-card-footer">
            <span class="goal-pct">${pct}% complete</span>
            <div class="goal-footer-right">${contribHtml}${etaHtml}</div>
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
        ? `<span class="goal-streak"><i class="fas fa-fire"></i> ${streak} streak</span>`
        : `<span class="goal-streak goal-streak-empty"><i class="far fa-circle"></i> Start your streak</span>`;

    const lastCheckin = goal.lastCheckIn
        ? `<span class="goal-last-checkin">Last: ${formatDate(goal.lastCheckIn)}</span>`
        : '';

    return `
    <div class="goal-card goal-card-periodic" data-id="${goal.id}">
        <div class="goal-card-top">
            <div class="goal-icon-wrap" style="background:${hexToRgba(color, 0.12)};color:${color}">
                <i class="fas ${icon}"></i>
            </div>
            <div class="goal-title-area">
                <h3 class="goal-title">${escapeHtml(goal.title)}</h3>
                <span class="goal-freq-badge">${capitalize(goal.contributionFrequency || 'Monthly')}</span>
            </div>
            <div class="goal-card-actions">
                <button class="goal-action-btn" onclick="editGoal(${goal.id})" title="Edit">
                    <i class="fas fa-pen"></i>
                </button>
                <button class="goal-action-btn goal-action-delete" onclick="deleteGoalConfirm(${goal.id})" title="Delete">
                    <i class="fas fa-trash"></i>
                </button>
            </div>
        </div>
        <div class="goal-periodic-center">
            ${streakHtml}
            <span class="goal-periodic-amount">
                ${formatCurrency(goal.monthlyContribution)}<span class="goal-per-label">/${freqLabel}</span>
            </span>
        </div>
        <div class="goal-card-footer">
            ${lastCheckin}
            <button class="btn goal-checkin-btn" style="background:${color};color:white" onclick="checkInGoal(${goal.id})">
                <i class="fas fa-check"></i> Check In
            </button>
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
    selectedColor = goalData ? (goalData.color || '#0FB9A8')     : '#0FB9A8';

    setGoalType(goalData ? (goalData.goalType || 'target') : 'target');
    refreshIconPicker();
    refreshColorPicker();

    document.getElementById('goalModal').classList.remove('hidden');
}

function closeGoalModal() {
    document.getElementById('goalModal').classList.add('hidden');
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
        `<button type="button" class="icon-pick-btn" data-icon="${icon}" title="${label}" onclick="selectIcon('${icon}')">
            <i class="fas ${icon}"></i>
        </button>`
    ).join('');
}

function buildColorPicker() {
    const el = document.getElementById('colorPicker');
    el.innerHTML = COLORS.map(color =>
        `<button type="button" class="color-pick-btn" data-color="${color}" style="background:${color}" onclick="selectColor('${color}')"></button>`
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

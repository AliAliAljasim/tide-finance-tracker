// Global variables for charts
let accountChart = null;
let networthChart = null;

// Format currency
function formatCurrency(amount) {
    return new Intl.NumberFormat('en-US', {
        style: 'currency',
        currency: 'USD'
    }).format(amount);
}

// Format percentage
function formatPercentage(value) {
    return (value * 100).toFixed(1) + '%';
}

// Show/hide loading overlay
function showLoading() {
    document.getElementById('loadingOverlay').classList.remove('hidden');
}

function hideLoading() {
    document.getElementById('loadingOverlay').classList.add('hidden');
}

// Update last update timestamp
function updateTimestamp() {
    const el = document.getElementById('lastUpdate');
    if (el) {
        const now = new Date();
        el.textContent = now.toLocaleString();
    }
}

// Load dashboard data
async function loadDashboardData() {
    try {
        const response = await fetch('/api/dashboard-data');
        const data = await response.json();

        if (data.error) {
            throw new Error(data.error);
        }

        // Update account list and chart
        updateAccountsList(data.accounts);
        updateAccountChart(data.accounts);

        updateTimestamp();
    } catch (error) {
        console.error('Error loading dashboard data:', error);
        alert('Failed to load dashboard data: ' + error.message);
    }
}

// Load spending breakdown
async function loadSpendingBreakdown() {
    try {
        const response = await fetch('/api/spending-breakdown');
        const data = await response.json();

        if (data.error) {
            throw new Error(data.error);
        }

        const categoryList = document.getElementById('categoryList');
        categoryList.innerHTML = '';

        data.categories.forEach(category => {
            const categoryDiv = document.createElement('div');
            categoryDiv.className = 'category-item';

            const percentUsed = category.budget > 0 ? (category.spent / category.budget) : 0;
            let progressClass = '';

            if (percentUsed >= 1) {
                progressClass = 'danger';
            } else if (percentUsed >= 0.8) {
                progressClass = 'warning';
            }

            categoryDiv.innerHTML = `
                <div class="category-header">
                    <span class="category-name">${category.name}</span>
                    <span class="category-amount">${formatCurrency(category.spent)}</span>
                </div>
                <div class="category-budget">
                    Budget: ${formatCurrency(category.budget)}
                    (${formatPercentage(percentUsed)} used)
                </div>
                <div class="progress-bar">
                    <div class="progress-fill ${progressClass}"
                         style="width: ${Math.min(percentUsed * 100, 100)}%"></div>
                </div>
            `;

            categoryList.appendChild(categoryDiv);
        });
    } catch (error) {
        console.error('Error loading spending breakdown:', error);
    }
}

// Load recent transactions
async function loadRecentTransactions() {
    try {
        const response = await fetch('/api/recent-transactions');
        const data = await response.json();

        if (data.error) {
            throw new Error(data.error);
        }

        const tbody = document.getElementById('transactionsBody');
        tbody.innerHTML = '';

        if (data.transactions.length === 0) {
            tbody.innerHTML = '<tr><td colspan="6" style="text-align: center; padding: 2rem; color: #6b7280;">No transactions found</td></tr>';
            return;
        }

        data.transactions.forEach(tx => {
            const row = document.createElement('tr');

            const typeClass = tx.type.toLowerCase();
            const amountClass = tx.type.toLowerCase();

            row.innerHTML = `
                <td>${tx.date}</td>
                <td>${tx.name}</td>
                <td>${tx.category}</td>
                <td>${tx.account}</td>
                <td><span class="transaction-type ${typeClass}">${tx.type}</span></td>
                <td class="transaction-amount ${amountClass}">${formatCurrency(tx.amount)}</td>
            `;

            tbody.appendChild(row);
        });
    } catch (error) {
        console.error('Error loading transactions:', error);
    }
}

// Load networth history
async function loadNetworthHistory() {
    try {
        const response = await fetch('/api/networth-history');
        const data = await response.json();

        if (data.error) {
            throw new Error(data.error);
        }

        updateNetworthChart(data.history);
    } catch (error) {
        console.error('Error loading networth history:', error);
    }
}

// Render accounts as a list
function updateAccountsList(accounts) {
    const accountData = [
        { label: 'Chequing', value: accounts.chequing || 0, color: 'rgba(37, 99, 235, 1)' },
        { label: 'Cash',     value: accounts.cash     || 0, color: 'rgba(16, 185, 129, 1)' },
        { label: 'TFSA',     value: accounts.tfsa     || 0, color: 'rgba(139, 92, 246, 1)' }
    ];

    const total = accountData.reduce((sum, a) => sum + a.value, 0);

    const listEl = document.getElementById('accountListItems');
    const totalEl = document.getElementById('accountListTotal');
    if (!listEl || !totalEl) return;

    listEl.innerHTML = accountData.map(a => `
        <div class="acct-row">
            <span class="acct-dot" style="background:${a.color}"></span>
            <span class="acct-name">${a.label}</span>
            <span class="acct-balance">${formatCurrency(a.value)}</span>
        </div>
    `).join('');

    totalEl.innerHTML = `
        <div class="acct-row acct-row-total">
            <span class="acct-name">Total</span>
            <span class="acct-balance acct-balance-total">${formatCurrency(total)}</span>
        </div>
    `;
}

// Update account distribution chart
function updateAccountChart(accounts) {
    const ctx = document.getElementById('accountChart');

    if (!ctx) {
        console.error('Account chart canvas not found');
        return;
    }

    console.log('Updating account chart with data:', accounts);

    if (accountChart) {
        accountChart.destroy();
    }

    // Build arrays with only non-zero accounts
    const accountData = [
        { label: 'Chequing', value: accounts.chequing || 0, color: 'rgba(37, 99, 235, 0.8)', borderColor: 'rgba(37, 99, 235, 1)' },
        { label: 'Cash', value: accounts.cash || 0, color: 'rgba(16, 185, 129, 0.8)', borderColor: 'rgba(16, 185, 129, 1)' },
        { label: 'TFSA', value: accounts.tfsa || 0, color: 'rgba(139, 92, 246, 0.8)', borderColor: 'rgba(139, 92, 246, 1)' }
    ];

    // Filter out accounts with zero balance
    const filteredData = accountData.filter(account => account.value > 0);

    // If no accounts have balance, show a placeholder
    if (filteredData.length === 0) {
        console.log('No account data to display');
        // You could show an empty state message here
        return;
    }

    const labels = filteredData.map(account => account.label);
    const data = filteredData.map(account => account.value);
    const backgroundColor = filteredData.map(account => account.color);
    const borderColor = filteredData.map(account => account.borderColor);

    console.log('Filtered chart data:', { labels, data });

    accountChart = new Chart(ctx, {
        type: 'doughnut',
        data: {
            labels: labels,
            datasets: [{
                data: data,
                backgroundColor: backgroundColor,
                borderColor: borderColor,
                borderWidth: 2
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: true,
            aspectRatio: 1,
            plugins: {
                legend: {
                    position: 'bottom',
                    labels: {
                        padding: 10,
                        font: {
                            size: 11
                        },
                        usePointStyle: true
                    }
                },
                tooltip: {
                    callbacks: {
                        label: function(context) {
                            const label = context.label || '';
                            const value = formatCurrency(context.parsed);
                            const total = context.dataset.data.reduce((a, b) => a + b, 0);
                            const percentage = total > 0 ? ((context.parsed / total) * 100).toFixed(1) : 0;
                            return `${label}: ${value} (${percentage}%)`;
                        }
                    }
                }
            }
        }
    });
}

// Update networth chart
function updateNetworthChart(history) {
    const ctx = document.getElementById('networthChart');

    if (networthChart) {
        networthChart.destroy();
    }

    const labels = history.map(h => h.monthKey);
    const totals = history.map(h => h.total);
    const chequing = history.map(h => h.chequing);
    const cash = history.map(h => h.cash);
    const tfsa = history.map(h => h.tfsa);

    networthChart = new Chart(ctx, {
        type: 'line',
        data: {
            labels: labels,
            datasets: [
                {
                    label: 'Total Net Worth',
                    data: totals,
                    borderColor: 'rgba(139, 92, 246, 1)',
                    backgroundColor: 'rgba(139, 92, 246, 0.1)',
                    borderWidth: 3,
                    tension: 0.4,
                    fill: true
                },
                {
                    label: 'Chequing',
                    data: chequing,
                    borderColor: 'rgba(37, 99, 235, 1)',
                    backgroundColor: 'rgba(37, 99, 235, 0.1)',
                    borderWidth: 2,
                    tension: 0.4,
                    fill: false
                },
                {
                    label: 'Cash',
                    data: cash,
                    borderColor: 'rgba(16, 185, 129, 1)',
                    backgroundColor: 'rgba(16, 185, 129, 0.1)',
                    borderWidth: 2,
                    tension: 0.4,
                    fill: false
                },
                {
                    label: 'TFSA',
                    data: tfsa,
                    borderColor: 'rgba(245, 158, 11, 1)',
                    backgroundColor: 'rgba(245, 158, 11, 0.1)',
                    borderWidth: 2,
                    tension: 0.4,
                    fill: false
                }
            ]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            interaction: {
                mode: 'index',
                intersect: false
            },
            plugins: {
                legend: {
                    position: 'bottom',
                    labels: {
                        padding: 15,
                        font: {
                            size: 12
                        }
                    }
                },
                tooltip: {
                    callbacks: {
                        label: function(context) {
                            return context.dataset.label + ': ' + formatCurrency(context.parsed.y);
                        }
                    }
                }
            },
            scales: {
                y: {
                    beginAtZero: true,
                    ticks: {
                        callback: function(value) {
                            return formatCurrency(value);
                        }
                    }
                }
            }
        }
    });
}

// Refresh all data
async function refreshData() {
    showLoading();

    try {
        await Promise.all([
            loadDashboardData(),
            loadNetworthHistory()
        ]);
    } catch (error) {
        console.error('Error refreshing data:', error);
    } finally {
        hideLoading();
    }
}

// Check if the current month's diary is filled out and show reminder if not
async function checkDiaryReminder() {
    // Don't show diary reminder while onboarding is active
    if (typeof ONBOARDING_COMPLETE !== 'undefined' && !ONBOARDING_COMPLETE) return;
    // Only show once per browser session
    if (sessionStorage.getItem('diaryReminderShown')) return;
    sessionStorage.setItem('diaryReminderShown', 'true');

    const now = new Date();
    const monthKey = now.getFullYear() + '-' + String(now.getMonth() + 1).padStart(2, '0');

    try {
        const response = await fetch(`/api/diary/${monthKey}`);
        const data = await response.json();

        if (!data.exists) {
            const monthLabel = now.toLocaleString('default', { month: 'long', year: 'numeric' });
            document.getElementById('diaryReminderMonth').textContent = monthLabel;
            document.getElementById('diaryReminderModal').classList.remove('hidden');
        }
    } catch (error) {
        console.error('Error checking diary status:', error);
    }
}

function dismissDiaryReminder() {
    document.getElementById('diaryReminderModal').classList.add('hidden');
}

// Initialize dashboard on page load
document.addEventListener('DOMContentLoaded', function() {
    refreshData();
    checkDiaryReminder();

    if (typeof ONBOARDING_COMPLETE !== 'undefined' && !ONBOARDING_COMPLETE) {
        obInit();
    }

    // Auto-refresh every 5 minutes
    setInterval(refreshData, 5 * 60 * 1000);
});

// ===== Onboarding Checklist =====

const obState = {
    completed: new Set([1]),
    attempted: new Set([1]),
    categories: []
};

async function obInit() {
    document.getElementById('onboardingModal').classList.add('show');
    obUpdateProgress();

    // Pre-fill income & savings from dashboard data
    try {
        const res = await fetch('/api/dashboard-data');
        const data = await res.json();
        if (data.settings) {
            if (data.settings.hourlyWage) document.getElementById('obHourlyWage').value = data.settings.hourlyWage;
            if (data.settings.hoursPerWeek) document.getElementById('obHoursPerWeek').value = data.settings.hoursPerWeek;
            if (data.settings.savingsTargetPercent) document.getElementById('obSavingsTarget').value = data.settings.savingsTargetPercent;
        }
    } catch (e) {}

    // Load budget categories for step 5
    try {
        const res = await fetch('/api/budget-categories');
        const data = await res.json();
        obState.categories = data.categories || [];
        obRenderCategories(obState.categories);
    } catch (e) {}

    // Wire up ticker autocomplete (stocks.js is loaded conditionally)
    if (typeof initializeTickerAutocomplete === 'function') {
        initializeTickerAutocomplete('obTicker', 'obTickerDropdown', 'obTickerSymbol', 'obTickerName');
    }
}

function obToggle(n) {
    const item = document.getElementById('obStep' + n);
    if (!item || item.classList.contains('completed')) return;
    const isExpanded = item.classList.contains('expanded');
    // Collapse all
    [2, 3, 4, 5].forEach(i => {
        const el = document.getElementById('obStep' + i);
        if (el) el.classList.remove('expanded');
    });
    if (!isExpanded) item.classList.add('expanded');
}

function obUpdateProgress() {
    const done = obState.completed.size;
    const pct = (done / 5) * 100;
    document.getElementById('onboardingProgressFill').style.width = pct + '%';
    document.getElementById('onboardingProgressLabel').textContent = done + ' / 5 complete';
    // Enable Done when steps 2–5 are all attempted
    const allAttempted = [2, 3, 4, 5].every(n => obState.attempted.has(n));
    document.getElementById('obDoneBtn').disabled = !allAttempted;
}

function obMarkStep(n) {
    const item = document.getElementById('obStep' + n);
    if (!item) return;
    item.classList.remove('expanded');
    item.classList.add('completed');
    obState.completed.add(n);
    obState.attempted.add(n);
    obUpdateProgress();
}

async function obAddHolding() {
    const ticker = document.getElementById('obTickerSymbol').value ||
                   document.getElementById('obTicker').value.trim().toUpperCase();
    const name   = document.getElementById('obTickerName').value || ticker;
    const accountType = document.getElementById('obAccountType').value;
    const shares  = parseFloat(document.getElementById('obShares').value);
    const avgCost = parseFloat(document.getElementById('obAvgCost').value) || 0;

    if (!ticker || isNaN(shares) || shares <= 0) {
        alert('Please enter a ticker and a valid number of shares.');
        return;
    }

    try {
        const res = await fetch('/api/add-holding', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ ticker, name, accountType, shares, avgCost })
        });
        const data = await res.json();
        if (data.error) throw new Error(data.error);

        // Show tag
        const tag = document.createElement('div');
        tag.className = 'onboarding-holding-tag';
        tag.innerHTML = `<span><strong>${ticker}</strong> &nbsp;·&nbsp; ${accountType} &nbsp;·&nbsp; ${shares} shares @ $${avgCost.toFixed(2)}</span>`;
        document.getElementById('obHoldingsList').appendChild(tag);

        // Clear inputs
        document.getElementById('obTicker').value = '';
        document.getElementById('obTickerSymbol').value = '';
        document.getElementById('obTickerName').value = '';
        document.getElementById('obShares').value = '';
        document.getElementById('obAvgCost').value = '';

        // Enable "Mark as done"
        const doneBtn = document.getElementById('obStep2DoneBtn');
        doneBtn.disabled = false;
        obState.attempted.add(2);
        obUpdateProgress();
    } catch (e) {
        alert('Failed to add holding: ' + e.message);
    }
}

async function obSaveIncome() {
    const wage  = parseFloat(document.getElementById('obHourlyWage').value);
    const hours = parseFloat(document.getElementById('obHoursPerWeek').value);
    if (isNaN(wage) || isNaN(hours) || wage < 0 || hours < 0) {
        alert('Please enter a valid wage and hours per week.');
        return;
    }
    try {
        const res = await fetch('/api/settings/update', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ hourlyWage: wage, hoursPerWeek: hours })
        });
        const data = await res.json();
        if (data.error) throw new Error(data.error);
        document.getElementById('obStep3Success').classList.add('show');
        setTimeout(() => obMarkStep(3), 700);
    } catch (e) {
        alert('Failed to save: ' + e.message);
    }
}

async function obSaveSavings() {
    const pct = parseFloat(document.getElementById('obSavingsTarget').value);
    if (isNaN(pct) || pct < 0 || pct > 100) {
        alert('Please enter a valid savings percentage between 0 and 100.');
        return;
    }
    try {
        const res = await fetch('/api/settings/update', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ savingsTargetPercent: pct / 100 })
        });
        const data = await res.json();
        if (data.error) throw new Error(data.error);
        document.getElementById('obStep4Success').classList.add('show');
        setTimeout(() => obMarkStep(4), 700);
    } catch (e) {
        alert('Failed to save: ' + e.message);
    }
}

function obRenderCategories(categories) {
    const container = document.getElementById('obCategoriesList');
    if (!container) return;
    if (!categories.length) {
        container.innerHTML = '<span class="onboarding-step-hint">No categories found.</span>';
        return;
    }
    container.innerHTML = categories.map(cat => `
        <div class="onboarding-form-group">
            <label>${cat.name} ($/month)</label>
            <input type="number" class="ob-cat-input" data-cat-id="${cat.id}"
                   value="${cat.monthly_budget}" min="0" step="1">
        </div>
    `).join('');
}

async function obSaveBudget() {
    const inputs = document.querySelectorAll('.ob-cat-input');
    const categories = Array.from(inputs).map(inp => ({
        id: inp.dataset.catId,
        monthly_budget: parseFloat(inp.value) || 0
    }));
    try {
        const res = await fetch('/api/settings/update', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ categories })
        });
        const data = await res.json();
        if (data.error) throw new Error(data.error);
        document.getElementById('obStep5Success').classList.add('show');
        setTimeout(() => obMarkStep(5), 700);
    } catch (e) {
        alert('Failed to save budget: ' + e.message);
    }
}

async function obComplete() {
    try {
        await fetch('/api/complete-onboarding', { method: 'POST' });
    } catch (e) {}
    document.getElementById('onboardingModal').classList.remove('show');
}

function obSkip() {
    obComplete();
}

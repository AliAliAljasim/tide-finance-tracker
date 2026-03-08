// Format currency
function formatCurrency(amount) {
    return new Intl.NumberFormat('en-US', {
        style: 'currency',
        currency: 'USD'
    }).format(amount);
}

// Format percentage
function formatPercentage(value) {
    return (value * 100).toFixed(2) + '%';
}

// Show/hide loading overlay
function showLoading() {
    document.getElementById('loadingOverlay').classList.remove('hidden');
}

function hideLoading() {
    document.getElementById('loadingOverlay').classList.add('hidden');
}

// Update timestamp
function updateTimestamp() {
    const el = document.getElementById('lastUpdate');
    if (!el) return;
    el.textContent = new Date().toLocaleString();
}

// Chart instances
let allocationChart = null;
let performanceChart = null;

// Chart color palette
const chartColors = [
    '#2563eb', '#10b981', '#f59e0b', '#ef4444', '#8b5cf6',
    '#ec4899', '#06b6d4', '#84cc16', '#f97316', '#6366f1',
    '#14b8a6', '#e11d48', '#0ea5e9', '#a855f7', '#22c55e'
];

// Load TFSA Summary & Stats
async function loadTFSASummary() {
    try {
        const response = await fetch('/api/tfsa-summary');
        const data = await response.json();

        if (data.error) {
            throw new Error(data.error);
        }

        // Update stats strip
        document.getElementById('marketValue').textContent = formatCurrency(data.marketValue);
        document.getElementById('gainLoss').textContent = formatCurrency(data.gainLoss);

        // Update gain/loss color
        const gainLossEl = document.getElementById('gainLoss');
        gainLossEl.style.color = data.gainLoss >= 0 ? 'var(--success-color)' : 'var(--danger-color)';

        updateTimestamp();
    } catch (error) {
        console.error('Error loading TFSA summary:', error);
    }
}

// Load Holdings — grouped by account
let holdingsData = [];
let registeredAccountKeys = [];
async function loadHoldings() {
    try {
        const [holdingsResp, accountsResp] = await Promise.all([
            fetch('/api/tfsa-holdings'),
            fetch('/api/investment-accounts')
        ]);
        const data = await holdingsResp.json();
        const accountsData = await accountsResp.json();

        if (data.error) throw new Error(data.error);

        holdingsData = data.holdings;

        const container = document.getElementById('accountsContainer');
        container.innerHTML = '';

        // Build holdings map grouped by account type
        let totalBookValue = 0;
        const accountMap = {};
        data.holdings.forEach(h => {
            totalBookValue += h.bookValue;
            const acct = h.accountType || 'TFSA';
            if (!accountMap[acct]) {
                accountMap[acct] = { holdings: [], marketValue: 0, bookValue: 0, gainLoss: 0 };
            }
            accountMap[acct].holdings.push(h);
            accountMap[acct].marketValue += h.marketValue;
            accountMap[acct].bookValue += h.bookValue;
            accountMap[acct].gainLoss += h.gainLoss;
        });

        // Ensure every registered account has a card, even with no holdings
        const registeredAccounts = (!accountsData.error && accountsData.accounts) ? accountsData.accounts : [];
        registeredAccounts.forEach(a => {
            if (!accountMap[a.label]) {
                accountMap[a.label] = { holdings: [], marketValue: 0, bookValue: 0, gainLoss: 0 };
            }
        });

        // Track registered account keys (lowercase) for the "Open new account" modal
        registeredAccountKeys = registeredAccounts
            .map(a => a.key.toLowerCase());

        const fhsaNeedsOpenYear = accountsData.fhsaNeedsOpenYear || false;

        document.getElementById('bookValue').textContent = formatCurrency(totalBookValue);

        if (Object.keys(accountMap).length === 0) {
            renderAllocationChart([]);
            renderPerformanceChart([]);
        } else {
            // Render one card per account — clicking navigates to account detail page
            Object.entries(accountMap).forEach(([acctType, acct]) => {
                const acctKey = acctType.toLowerCase().replace(/[^a-z]/g, '');
                const acctSlug = acctType.toLowerCase().replace(/\s+/g, '-');
                const hasHoldings = acct.holdings.length > 0;
                const glClass = acct.gainLoss >= 0 ? 'positive' : 'negative';
                const returnPct = acct.bookValue > 0 ? (acct.gainLoss / acct.bookValue) * 100 : 0;
                const isFHSAMissingYear = acctType === 'FHSA' && fhsaNeedsOpenYear;

                const card = document.createElement('div');
                card.className = 'account-card account-card-link';
                card.addEventListener('click', () => { window.location.href = `/investments/${acctSlug}`; });

                const holdingWord = acct.holdings.length !== 1 ? 's' : '';
                const setupBadge = isFHSAMissingYear
                    ? '<span class="fhsa-setup-badge" title="Open year not set — click to configure"><i class="fas fa-asterisk"></i></span>'
                    : '';

                card.innerHTML = hasHoldings ? `
                    <div class="account-card-header">
                        <div class="account-card-title">
                            <span class="account-badge account-${acctKey}">${acctType}</span>
                            ${setupBadge}
                            <span class="account-holding-count">${acct.holdings.length} holding${holdingWord}</span>
                        </div>
                        <div class="account-card-stats">
                            <div class="account-stat">
                                <span class="account-stat-label">Market Value</span>
                                <span class="account-stat-value">${formatCurrency(acct.marketValue)}</span>
                            </div>
                            <div class="account-stat">
                                <span class="account-stat-label">Book Value</span>
                                <span class="account-stat-value">${formatCurrency(acct.bookValue)}</span>
                            </div>
                            <div class="account-stat">
                                <span class="account-stat-label">Gain / Loss</span>
                                <span class="account-stat-value ${glClass}">${acct.gainLoss >= 0 ? '+' : ''}${formatCurrency(acct.gainLoss)} <small>(${returnPct >= 0 ? '+' : ''}${returnPct.toFixed(1)}%)</small></span>
                            </div>
                        </div>
                        <span class="account-arrow"><i class="fas fa-chevron-right"></i></span>
                    </div>
                ` : `
                    <div class="account-card-header">
                        <div class="account-card-title">
                            <span class="account-badge account-${acctKey}">${acctType}</span>
                            ${setupBadge}
                            <span class="account-holding-count">No holdings</span>
                        </div>
                        <span class="account-arrow"><i class="fas fa-chevron-right"></i></span>
                    </div>
                `;

                container.appendChild(card);
            });

            renderAllocationChart(data.holdings);
            renderPerformanceChart(data.holdings);
        }

        // Always show "Open new account" button at the bottom
        const openBtn = document.createElement('button');
        openBtn.className = 'btn-open-new-account';
        openBtn.type = 'button';
        openBtn.onclick = openNewAccountModal;
        openBtn.innerHTML = '<i class="fas fa-plus"></i> Open new account';
        container.appendChild(openBtn);
    } catch (error) {
        console.error('Error loading holdings:', error);
    }
}

// ===== CHARTS =====

function renderAllocationChart(holdings) {
    const ctx = document.getElementById('allocationChart').getContext('2d');

    if (allocationChart) {
        allocationChart.destroy();
    }

    if (holdings.length === 0) {
        const legendEl = document.getElementById('allocationLegend');
        legendEl.innerHTML = '<p class="empty-chart-msg">Add holdings to see allocation</p>';
        return;
    }

    const labels = holdings.map(h => h.ticker);
    const values = holdings.map(h => h.marketValue);
    const totalValue = values.reduce((a, b) => a + b, 0);
    const colors = holdings.map((_, i) => chartColors[i % chartColors.length]);

    allocationChart = new Chart(ctx, {
        type: 'doughnut',
        data: {
            labels: labels,
            datasets: [{
                data: values,
                backgroundColor: colors,
                borderWidth: 2,
                borderColor: '#ffffff',
                hoverBorderWidth: 3
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            cutout: '60%',
            plugins: {
                legend: { display: false },
                tooltip: {
                    callbacks: {
                        label: function(context) {
                            const pct = ((context.parsed / totalValue) * 100).toFixed(1);
                            return `${context.label}: ${formatCurrency(context.parsed)} (${pct}%)`;
                        }
                    }
                }
            }
        }
    });

    // Custom legend
    const legendEl = document.getElementById('allocationLegend');
    legendEl.innerHTML = '';
    holdings.forEach((h, i) => {
        const pct = totalValue > 0 ? ((h.marketValue / totalValue) * 100).toFixed(1) : 0;
        const item = document.createElement('div');
        item.className = 'legend-item';
        item.innerHTML = `
            <span class="legend-color" style="background: ${colors[i]}"></span>
            <span class="legend-ticker">${h.ticker}</span>
            <span class="legend-pct">${pct}%</span>
            <span class="legend-value">${formatCurrency(h.marketValue)}</span>
        `;
        legendEl.appendChild(item);
    });
}

function renderPerformanceChart(holdings) {
    const ctx = document.getElementById('performanceChart').getContext('2d');

    if (performanceChart) {
        performanceChart.destroy();
    }

    if (holdings.length === 0) {
        return;
    }

    const labels = holdings.map(h => h.ticker);
    const gainLossValues = holdings.map(h => h.gainLoss);
    const colors = gainLossValues.map(v => v >= 0 ? 'rgba(16, 185, 129, 0.8)' : 'rgba(239, 68, 68, 0.8)');
    const borderColors = gainLossValues.map(v => v >= 0 ? '#059669' : '#dc2626');

    performanceChart = new Chart(ctx, {
        type: 'bar',
        data: {
            labels: labels,
            datasets: [{
                label: 'Gain/Loss ($)',
                data: gainLossValues,
                backgroundColor: colors,
                borderColor: borderColors,
                borderWidth: 1,
                borderRadius: 4
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: { display: false },
                tooltip: {
                    callbacks: {
                        label: function(context) {
                            const holding = holdings[context.dataIndex];
                            const returnPct = holding.bookValue > 0 ? ((holding.gainLoss / holding.bookValue) * 100).toFixed(2) : 0;
                            return [
                                `Gain/Loss: ${formatCurrency(context.parsed.y)}`,
                                `Return: ${returnPct}%`,
                                `Book: ${formatCurrency(holding.bookValue)}`,
                                `Market: ${formatCurrency(holding.marketValue)}`
                            ];
                        }
                    }
                }
            },
            scales: {
                y: {
                    beginAtZero: true,
                    grid: { color: 'rgba(0,0,0,0.05)' },
                    ticks: {
                        callback: function(value) {
                            return formatCurrency(value);
                        }
                    }
                },
                x: {
                    grid: { display: false },
                    ticks: { font: { weight: 'bold' } }
                }
            }
        }
    });
}

// ===== EDIT / DELETE =====

// Delete confirmation
var pendingDelete = null;

function confirmDelete(type, id, description) {
    pendingDelete = { type, id };
    document.getElementById('deleteConfirmMessage').textContent = `Are you sure you want to delete this ${type}? (${description})`;
    document.getElementById('deleteConfirmModal').classList.add('show');
}

function closeDeleteConfirmModal() {
    document.getElementById('deleteConfirmModal').classList.remove('show');
    pendingDelete = null;
}

async function executeDelete() {
    if (!pendingDelete) return;

    const { type, id } = pendingDelete;
    const urlMap = {
        deposit: `/api/delete-tfsa-deposit/${id}`,
        trade: `/api/delete-tfsa-trade/${id}`,
        holding: `/api/delete-holding/${id}`,
        account: `/api/delete-account/${id}`
    };

    try {
        showLoading();
        closeDeleteConfirmModal();
        const response = await fetch(urlMap[type], { method: 'DELETE' });
        const result = await response.json();

        if (result.error) {
            throw new Error(result.error);
        }

        await refreshData();
    } catch (error) {
        console.error('Error deleting:', error);
        alert('Failed to delete: ' + error.message);
    } finally {
        hideLoading();
    }
}

// Edit Holding
function editHolding(id, ticker, name, shares, avgCost, accountType) {
    document.getElementById('editHoldingId').value = id;
    document.getElementById('editHoldingAccount').value = accountType || 'TFSA';
    document.getElementById('editHoldingTicker').value = ticker;
    document.getElementById('editHoldingName').value = name;
    document.getElementById('editHoldingShares').value = shares;
    document.getElementById('editHoldingAvgCost').value = avgCost;
    document.getElementById('editHoldingModal').classList.add('show');
}

function closeEditHoldingModal() {
    document.getElementById('editHoldingModal').classList.remove('show');
}

// Refresh all data
async function refreshData() {
    showLoading();

    try {
        await Promise.all([
            loadTFSASummary(),
            loadHoldings()
        ]);
    } catch (error) {
        console.error('Error refreshing data:', error);
    } finally {
        hideLoading();
    }
}

// Modal functions
function showDepositModal() {
    const modal = document.getElementById('depositModal');
    modal.classList.add('show');
    // Set today's date as default
    document.getElementById('depositDate').valueAsDate = new Date();
}

function closeDepositModal() {
    const modal = document.getElementById('depositModal');
    modal.classList.remove('show');
    document.getElementById('depositForm').reset();
}

function showTradeModal() {
    const modal = document.getElementById('tradeModal');
    modal.classList.add('show');
    // Set today's date as default
    document.getElementById('tradeDate').valueAsDate = new Date();
}

function closeTradeModal() {
    const modal = document.getElementById('tradeModal');
    modal.classList.remove('show');
    document.getElementById('tradeForm').reset();
    document.getElementById('totalCost').textContent = '$0.00';
    document.getElementById('tradeTickerSymbol').value = '';
    document.getElementById('tradeTickerDropdown').innerHTML = '';
    document.getElementById('tradeTickerDropdown').classList.remove('show');
}

function showHoldingModal() {
    const modal = document.getElementById('holdingModal');
    modal.classList.add('show');
}

function closeHoldingModal() {
    const modal = document.getElementById('holdingModal');
    modal.classList.remove('show');
    document.getElementById('holdingForm').reset();
    document.getElementById('holdingTickerSymbol').value = '';
    document.getElementById('holdingTickerDropdown').innerHTML = '';
    document.getElementById('holdingTickerDropdown').classList.remove('show');
}

// ===== OPEN NEW ACCOUNT MODAL =====

const ALL_ACCOUNT_TYPES = [
    { key: 'tfsa',  label: 'TFSA',  description: 'Tax-Free Savings Account' },
    { key: 'fhsa',  label: 'FHSA',  description: 'First Home Savings Account' },
    { key: 'rrsp',  label: 'RRSP',  description: 'Registered Retirement Savings Plan' },
    { key: 'resp',  label: 'RESP',  description: 'Registered Education Savings Plan' },
    { key: 'non-registered', label: 'Non-Registered', description: 'Non-Registered Investment Account' },
];

function openNewAccountModal() {
    const modal = document.getElementById('newAccountModal');
    const optionsContainer = document.getElementById('newAccountOptions');
    optionsContainer.innerHTML = '';

    ALL_ACCOUNT_TYPES.forEach(acct => {
        const isRegistered = registeredAccountKeys.includes(acct.key);
        const btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'new-account-option' + (isRegistered ? ' registered' : '');
        btn.disabled = isRegistered;
        btn.innerHTML = `
            <span class="new-account-option-label">${acct.label}</span>
            <span class="new-account-option-desc">${acct.description}</span>
            ${isRegistered
                ? '<span class="new-account-option-tag">Already open</span>'
                : '<i class="fas fa-chevron-right new-account-option-arrow"></i>'}
        `;
        if (!isRegistered) {
            btn.onclick = () => acct.key === 'fhsa' ? showFHSAYearStep() : addNewAccount(acct.key);
        }
        optionsContainer.appendChild(btn);
    });

    modal.classList.add('show');
}

function closeNewAccountModal() {
    document.getElementById('newAccountModal').classList.remove('show');
    showNewAccountStep1();
}

function showNewAccountStep1() {
    document.getElementById('newAccountStep1').style.display = '';
    document.getElementById('fhsaYearStep').style.display = 'none';
    document.getElementById('fhsaOpenYearInput').value = '';
    const err = document.getElementById('fhsaYearError');
    err.style.display = 'none';
    err.textContent = '';
}

function showFHSAYearStep() {
    document.getElementById('newAccountStep1').style.display = 'none';
    document.getElementById('fhsaYearStep').style.display = '';
    document.getElementById('fhsaOpenYearInput').focus();
}

async function confirmAddFHSA() {
    const input = document.getElementById('fhsaOpenYearInput');
    const errEl = document.getElementById('fhsaYearError');
    const year = parseInt(input.value, 10);
    const currentYear = new Date().getFullYear();

    if (!year || year < 2023 || year > currentYear) {
        errEl.textContent = `Please enter a year between 2023 and ${currentYear}.`;
        errEl.style.display = '';
        return;
    }
    errEl.style.display = 'none';
    await addNewAccount('fhsa', year);
}

async function addNewAccount(accountKey, fhsaOpenYear = null) {
    try {
        const profileResp = await fetch('/api/profile');
        const profileData = await profileResp.json();

        const currentAccounts = profileData.registeredAccounts || [];
        if (!currentAccounts.includes(accountKey)) {
            currentAccounts.push(accountKey);
        }

        const payload = { registeredAccounts: currentAccounts };
        if (accountKey === 'fhsa' && fhsaOpenYear) {
            payload.fhsaOpenYear = fhsaOpenYear;
        }

        const updateResp = await fetch('/api/settings/update', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });

        const result = await updateResp.json();
        if (result.success) {
            closeNewAccountModal();
            loadHoldings();
        } else {
            alert('Failed to open account. Please try again.');
        }
    } catch (error) {
        console.error('Error adding account:', error);
    }
}

// Calculate total cost in trade form
function updateTotalCost() {
    const shares = parseFloat(document.getElementById('tradeShares').value) || 0;
    const cost = parseFloat(document.getElementById('tradeCost').value) || 0;
    const fees = parseFloat(document.getElementById('tradeFees').value) || 0;
    const total = (shares * cost) + fees;
    document.getElementById('totalCost').textContent = formatCurrency(total);
}

// Ticker Autocomplete Functionality
let tickerSearchTimeout = null;

function initializeTickerAutocomplete(inputId, dropdownId, hiddenInputId, nameInputId = null) {
    const input = document.getElementById(inputId);
    const dropdown = document.getElementById(dropdownId);
    const hiddenInput = document.getElementById(hiddenInputId);
    const nameInput = nameInputId ? document.getElementById(nameInputId) : null;

    let selectedIndex = -1;
    let currentResults = [];

    // Search for tickers
    async function searchTickers(query) {
        if (!query || query.length < 1) {
            dropdown.innerHTML = '';
            dropdown.classList.remove('show');
            return;
        }

        try {
            const response = await fetch(`/api/tickers/search?q=${encodeURIComponent(query)}`);
            const data = await response.json();

            if (data.error) {
                throw new Error(data.error);
            }

            currentResults = data.tickers;
            displayResults(data.tickers);
        } catch (error) {
            console.error('Error searching tickers:', error);
            dropdown.innerHTML = '<div class="ticker-item error">Error loading tickers</div>';
            dropdown.classList.add('show');
        }
    }

    // Display search results
    function displayResults(tickers) {
        if (tickers.length === 0) {
            dropdown.innerHTML = '<div class="ticker-item no-results">No tickers found</div>';
            dropdown.classList.add('show');
            return;
        }

        dropdown.innerHTML = '';
        tickers.forEach((ticker, index) => {
            const item = document.createElement('div');
            item.className = 'ticker-item';

            // Show exchange if available
            const exchangeInfo = ticker.exchange && ticker.exchange !== 'N/A'
                ? `<div class="ticker-exchange">${ticker.exchange}</div>`
                : '';

            item.innerHTML = `
                <div class="ticker-symbol">${ticker.symbol}</div>
                <div class="ticker-name">${ticker.name}</div>
                <div class="ticker-type">${ticker.type}</div>
                ${exchangeInfo}
            `;

            item.addEventListener('click', () => selectTicker(ticker));
            item.addEventListener('mouseenter', () => {
                selectedIndex = index;
                highlightItem(index);
            });

            dropdown.appendChild(item);
        });

        dropdown.classList.add('show');
        selectedIndex = -1;
    }

    // Select a ticker
    function selectTicker(ticker) {
        input.value = `${ticker.symbol} - ${ticker.name}`;
        hiddenInput.value = ticker.symbol;

        if (nameInput) {
            nameInput.value = ticker.name;
        }

        dropdown.innerHTML = '';
        dropdown.classList.remove('show');
        currentResults = [];
        selectedIndex = -1;
    }

    // Highlight item
    function highlightItem(index) {
        const items = dropdown.querySelectorAll('.ticker-item');
        items.forEach((item, i) => {
            if (i === index) {
                item.classList.add('selected');
            } else {
                item.classList.remove('selected');
            }
        });
    }

    // Input event listener
    input.addEventListener('input', function(e) {
        clearTimeout(tickerSearchTimeout);
        const query = e.target.value.trim();

        tickerSearchTimeout = setTimeout(() => {
            searchTickers(query);
        }, 300); // Debounce search by 300ms
    });

    // Keyboard navigation
    input.addEventListener('keydown', function(e) {
        const items = dropdown.querySelectorAll('.ticker-item:not(.no-results):not(.error)');

        if (e.key === 'ArrowDown') {
            e.preventDefault();
            if (selectedIndex < items.length - 1) {
                selectedIndex++;
                highlightItem(selectedIndex);
                items[selectedIndex].scrollIntoView({ block: 'nearest' });
            }
        } else if (e.key === 'ArrowUp') {
            e.preventDefault();
            if (selectedIndex > 0) {
                selectedIndex--;
                highlightItem(selectedIndex);
                items[selectedIndex].scrollIntoView({ block: 'nearest' });
            }
        } else if (e.key === 'Enter' && selectedIndex >= 0 && selectedIndex < currentResults.length) {
            e.preventDefault();
            selectTicker(currentResults[selectedIndex]);
        } else if (e.key === 'Escape') {
            dropdown.innerHTML = '';
            dropdown.classList.remove('show');
            currentResults = [];
            selectedIndex = -1;
        }
    });

    // Close dropdown when clicking outside
    document.addEventListener('click', function(e) {
        if (e.target !== input && !dropdown.contains(e.target)) {
            dropdown.innerHTML = '';
            dropdown.classList.remove('show');
            currentResults = [];
            selectedIndex = -1;
        }
    });

    // Clear hidden input and name when text is cleared
    input.addEventListener('blur', function() {
        setTimeout(() => {
            if (!input.value.trim()) {
                hiddenInput.value = '';
                if (nameInput) {
                    nameInput.value = '';
                }
            }
        }, 200);
    });
}

// Load investment account types and populate selectors
async function loadInvestmentAccounts() {
    try {
        const response = await fetch('/api/investment-accounts');
        const data = await response.json();
        if (data.error) return;

        const selectors = ['tradeAccount', 'holdingAccount', 'editHoldingAccount'];
        selectors.forEach(id => {
            const select = document.getElementById(id);
            if (!select) return;
            select.innerHTML = '';
            data.accounts.forEach(acct => {
                const option = document.createElement('option');
                option.value = acct.key;
                option.textContent = acct.label;
                select.appendChild(option);
            });
        });
    } catch (error) {
        console.error('Error loading accounts:', error);
    }
}

// Handle form submissions
document.addEventListener('DOMContentLoaded', function() {
    // Only run page-specific setup on the investments overview page
    if (!document.getElementById('accountsContainer')) return;

    // Load account types for dropdowns
    loadInvestmentAccounts();

    // Trade form
    document.getElementById('tradeForm').addEventListener('submit', async function(e) {
        e.preventDefault();

        const tickerSymbol = document.getElementById('tradeTickerSymbol').value;
        if (!tickerSymbol) {
            alert('Please select a valid ticker from the dropdown');
            return;
        }

        const tradeData = {
            date: document.getElementById('tradeDate').value,
            ticker: tickerSymbol,
            accountType: document.getElementById('tradeAccount').value,
            shares: parseFloat(document.getElementById('tradeShares').value),
            costPerShare: parseFloat(document.getElementById('tradeCost').value),
            fees: parseFloat(document.getElementById('tradeFees').value) || 0
        };

        try {
            showLoading();
            const response = await fetch('/api/add-tfsa-trade', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(tradeData)
            });

            const result = await response.json();
            if (result.error) throw new Error(result.error);

            closeTradeModal();
            await refreshData();
        } catch (error) {
            console.error('Error adding trade:', error);
            alert('Failed to add trade: ' + error.message);
        } finally {
            hideLoading();
        }
    });

    // Holding form
    document.getElementById('holdingForm').addEventListener('submit', async function(e) {
        e.preventDefault();

        const tickerSymbol = document.getElementById('holdingTickerSymbol').value;
        if (!tickerSymbol) {
            alert('Please select a valid ticker from the dropdown');
            return;
        }

        const holdingData = {
            ticker: tickerSymbol,
            accountType: document.getElementById('holdingAccount').value,
            name: document.getElementById('holdingName').value,
            shares: parseFloat(document.getElementById('holdingShares').value),
            avgCost: parseFloat(document.getElementById('holdingAvgCost').value)
        };

        try {
            showLoading();
            const response = await fetch('/api/add-holding', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(holdingData)
            });

            const result = await response.json();
            if (result.error) throw new Error(result.error);

            closeHoldingModal();
            await refreshData();
        } catch (error) {
            console.error('Error adding holding:', error);
            alert('Failed to add holding: ' + error.message);
        } finally {
            hideLoading();
        }
    });

    // Edit Holding form
    document.getElementById('editHoldingForm').addEventListener('submit', async function(e) {
        e.preventDefault();
        const id = document.getElementById('editHoldingId').value;

        try {
            showLoading();
            const response = await fetch(`/api/update-holding/${id}`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    ticker: document.getElementById('editHoldingTicker').value,
                    accountType: document.getElementById('editHoldingAccount').value,
                    name: document.getElementById('editHoldingName').value,
                    shares: parseFloat(document.getElementById('editHoldingShares').value),
                    avgCost: parseFloat(document.getElementById('editHoldingAvgCost').value)
                })
            });

            const result = await response.json();
            if (result.error) throw new Error(result.error);

            closeEditHoldingModal();
            await refreshData();
        } catch (error) {
            console.error('Error updating holding:', error);
            alert('Failed to update holding: ' + error.message);
        } finally {
            hideLoading();
        }
    });

    // Delete confirmation button
    document.getElementById('confirmDeleteBtn').addEventListener('click', executeDelete);

    // Update total cost when trade inputs change
    ['tradeShares', 'tradeCost', 'tradeFees'].forEach(id => {
        document.getElementById(id).addEventListener('input', updateTotalCost);
    });

    // Close modals when clicking outside
    window.addEventListener('click', function(event) {
        const modals = ['tradeModal', 'holdingModal', 'editHoldingModal', 'deleteConfirmModal', 'newAccountModal'];
        modals.forEach(modalId => {
            const modal = document.getElementById(modalId);
            if (event.target === modal) {
                modal.classList.remove('show');
            }
        });
    });

    // Initialize ticker autocomplete
    initializeTickerAutocomplete('tradeTicker', 'tradeTickerDropdown', 'tradeTickerSymbol');
    initializeTickerAutocomplete('holdingTicker', 'holdingTickerDropdown', 'holdingTickerSymbol', 'holdingName');

    // Initialize page
    refreshData();

    // Auto-refresh every 5 minutes
    setInterval(refreshData, 5 * 60 * 1000);
});

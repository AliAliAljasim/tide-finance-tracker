let currentStep = 1;

// Navigation functions
function nextStep(step) {
    // Validate current step before proceeding
    if (!validateStep(currentStep)) {
        return;
    }

    // Hide current step
    document.getElementById(`step${currentStep}`).classList.remove('active');

    // Show next step
    currentStep = step;
    document.getElementById(`step${currentStep}`).classList.add('active');

    // Update progress bar
    updateProgressBar();

    // If moving to Step 5 (balances), show only relevant account fields
    if (step === 5) {
        updateAccountBalanceFields();
    }

    // Scroll to top
    window.scrollTo({ top: 0, behavior: 'smooth' });
}

function prevStep(step) {
    // Hide current step
    document.getElementById(`step${currentStep}`).classList.remove('active');

    // Show previous step
    currentStep = step;
    document.getElementById(`step${currentStep}`).classList.add('active');

    // Update progress bar
    updateProgressBar();

    // Scroll to top
    window.scrollTo({ top: 0, behavior: 'smooth' });
}

// Update progress bar
function updateProgressBar() {
    const totalSteps = 7;
    const percentage = Math.round((currentStep / totalSteps) * 100);

    // Update step number
    document.getElementById('currentStepNumber').textContent = currentStep;

    // Update percentage
    document.getElementById('progressPercent').textContent = percentage;

    // Update progress bar width
    document.getElementById('progressBar').style.width = percentage + '%';
}

// Validation functions
function validateStep(step) {
    switch(step) {
        case 1:
            return validateStep1(); // Name & Location
        case 2:
            return validateStep2(); // Employment, Life Stage, Household
        case 3:
            return validateStep3(); // Financial Goals
        case 4:
            return validateStep4(); // Registered Accounts (optional)
        case 5:
            return validateStep5(); // Initial Account Balances
        case 6:
            return validateStep6(); // Budget Categories
        case 7:
            return validateStep7(); // Email & Password
        default:
            return true;
    }
}

function validateStep1() {
    const fullName = document.getElementById('fullName').value.trim();
    const provinceFieldGroup = document.getElementById('provinceFieldGroup');

    if (!fullName) {
        alert('Please enter your full name');
        document.getElementById('fullName').focus();
        return false;
    }

    // Show province field if not already shown
    if (provinceFieldGroup.classList.contains('hidden')) {
        showProvinceField();
        alert('Please select your province');
        return false;
    }

    const province = document.getElementById('province').value;

    if (!province) {
        alert('Please select your province');
        document.getElementById('province').focus();
        return false;
    }

    return true;
}

function validateStep2() {
    const lifeStage = document.getElementById('lifeStage').value;
    const employmentFieldGroup = document.getElementById('employmentFieldGroup');
    const householdFieldGroup = document.getElementById('householdFieldGroup');

    if (!lifeStage) {
        alert('Please select your life stage');
        document.getElementById('lifeStage').focus();
        return false;
    }

    // Show employment field if not already shown
    if (employmentFieldGroup.classList.contains('hidden')) {
        showEmploymentField();
        alert('Please select your employment status');
        return false;
    }

    const employmentStatus = document.getElementById('employmentStatus').value;

    if (!employmentStatus) {
        alert('Please select your employment status');
        document.getElementById('employmentStatus').focus();
        return false;
    }

    // Show household field if not already shown
    if (householdFieldGroup.classList.contains('hidden')) {
        showHouseholdField();
        alert('Please select your household status');
        return false;
    }

    const householdStatus = document.getElementById('householdStatus').value;

    if (!householdStatus) {
        alert('Please select your household status');
        document.getElementById('householdStatus').focus();
        return false;
    }

    return true;
}

function validateStep3() {
    const goals = document.querySelectorAll('input[name="goals"]:checked');

    if (goals.length === 0) {
        alert('Please select at least one financial goal');
        return false;
    }

    return true;
}

function validateStep4() {
    // Registered accounts are optional, so always return true
    return true;
}

function validateStep5() {
    // Account balances are optional, always return true
    return true;
}

function validateStep6() {
    // Budget categories are optional, always return true
    return true;
}

function validateStep7() {
    const email = document.getElementById('email').value.trim();
    const passwordFieldsGroup = document.getElementById('passwordFieldsGroup');

    if (!email || !isValidEmail(email)) {
        alert('Please enter a valid email address');
        document.getElementById('email').focus();
        return false;
    }

    // Show password fields if not already shown
    if (passwordFieldsGroup.classList.contains('hidden')) {
        showPasswordFields();
        alert('Please enter your password');
        return false;
    }

    const password = document.getElementById('password').value;
    const confirmPassword = document.getElementById('confirmPassword').value;

    if (!password || password.length < 6) {
        alert('Password must be at least 6 characters long');
        document.getElementById('password').focus();
        return false;
    }

    if (password !== confirmPassword) {
        alert('Passwords do not match');
        document.getElementById('confirmPassword').focus();
        return false;
    }

    return true;
}

function isValidEmail(email) {
    const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
    return emailRegex.test(email);
}

// Form submission
document.getElementById('signupForm').addEventListener('submit', async function(e) {
    e.preventDefault();

    // Only allow submission on step 7
    if (currentStep !== 7) {
        return;
    }

    // Show loading overlay
    document.getElementById('loadingOverlay').classList.remove('hidden');

    // Collect financial goals
    const financialGoals = Array.from(document.querySelectorAll('input[name="goals"]:checked'))
        .map(checkbox => checkbox.value);

    // Collect registered accounts
    const registeredAccounts = Array.from(document.querySelectorAll('input[name="accounts"]:checked'))
        .map(checkbox => checkbox.value);

    // Collect form data
    const formData = {
        fullName: document.getElementById('fullName').value.trim(),
        email: document.getElementById('email').value.trim(),
        password: document.getElementById('password').value,
        personalInfo: {
            province: document.getElementById('province').value,
            lifeStage: document.getElementById('lifeStage').value,
            employmentStatus: document.getElementById('employmentStatus').value,
            householdStatus: document.getElementById('householdStatus').value,
            financialGoals: financialGoals,
            registeredAccounts: registeredAccounts
        },
        accounts: {
            chequing: parseFloat(document.getElementById('chequingBalance').value) || 0,
            cash: parseFloat(document.getElementById('cashBalance').value) || 0,
            tfsa: parseFloat(document.getElementById('tfsaBalance').value) || 0,
            rrsp: parseFloat(document.getElementById('rrspBalance').value) || 0,
            resp: parseFloat(document.getElementById('respBalance').value) || 0,
            fhsa: parseFloat(document.getElementById('fhsaBalance').value) || 0
        },
        budget: {
            food: parseFloat(document.querySelector('[name="budgetFood"]').value) || 0,
            transport: parseFloat(document.querySelector('[name="budgetTransport"]').value) || 0,
            housing: parseFloat(document.querySelector('[name="budgetHousing"]').value) || 0,
            entertainment: parseFloat(document.querySelector('[name="budgetEntertainment"]').value) || 0,
            utilities: parseFloat(document.querySelector('[name="budgetUtilities"]').value) || 0,
            shopping: parseFloat(document.querySelector('[name="budgetShopping"]').value) || 0
        }
    };

    try {
        const response = await fetch('/api/signup', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify(formData)
        });

        const data = await response.json();

        if (data.error) {
            throw new Error(data.error);
        }

        // Check if user selected TFSA or FHSA — show questionnaire
        const hasTfsa = registeredAccounts.includes('tfsa');
        const hasFhsa = registeredAccounts.includes('fhsa');

        const tfsaBalance = parseFloat(document.getElementById('tfsaBalance').value) || 0;
        if (hasTfsa || hasFhsa) {
            showQuestionnaire(hasTfsa, hasFhsa, tfsaBalance);
        } else {
            window.location.href = '/';
        }
    } catch (error) {
        console.error('Signup error:', error);
        alert('Error creating account: ' + error.message);
    } finally {
        document.getElementById('loadingOverlay').classList.add('hidden');
    }
});

// Update total budget when category values change
function updateTotalBudget() {
    const food = parseFloat(document.querySelector('[name="budgetFood"]').value) || 0;
    const transport = parseFloat(document.querySelector('[name="budgetTransport"]').value) || 0;
    const housing = parseFloat(document.querySelector('[name="budgetHousing"]').value) || 0;
    const entertainment = parseFloat(document.querySelector('[name="budgetEntertainment"]').value) || 0;
    const utilities = parseFloat(document.querySelector('[name="budgetUtilities"]').value) || 0;
    const shopping = parseFloat(document.querySelector('[name="budgetShopping"]').value) || 0;

    const total = food + transport + housing + entertainment + utilities + shopping;

    const totalElement = document.getElementById('totalBudget');
    if (totalElement) {
        totalElement.textContent = new Intl.NumberFormat('en-US', {
            style: 'currency',
            currency: 'USD'
        }).format(total);
    }
}

// Show password while holding
function showPassword(targetId) {
    const input = document.getElementById(targetId);
    const button = document.querySelector(`[data-target="${targetId}"]`);
    const icon = button.querySelector('i');

    input.type = 'text';
    icon.classList.remove('fa-eye');
    icon.classList.add('fa-eye-slash');
}

// Hide password when released
function hidePassword(targetId) {
    const input = document.getElementById(targetId);
    const button = document.querySelector(`[data-target="${targetId}"]`);
    const icon = button.querySelector('i');

    input.type = 'password';
    icon.classList.remove('fa-eye-slash');
    icon.classList.add('fa-eye');
}

// Progressive disclosure for Step 1 (name -> province)
function showProvinceField() {
    const fullName = document.getElementById('fullName').value.trim();
    const provinceFieldGroup = document.getElementById('provinceFieldGroup');

    if (fullName && fullName.length >= 2 && provinceFieldGroup.classList.contains('hidden')) {
        provinceFieldGroup.classList.remove('hidden');
        provinceFieldGroup.classList.add('show');

        // Focus on province field after animation
        setTimeout(() => {
            document.getElementById('province').focus();
        }, 400);
    }
}

// Progressive disclosure for Step 2 (life stage -> employment)
function showEmploymentField() {
    const lifeStage = document.getElementById('lifeStage').value;
    const employmentFieldGroup = document.getElementById('employmentFieldGroup');

    if (lifeStage && employmentFieldGroup.classList.contains('hidden')) {
        employmentFieldGroup.classList.remove('hidden');
        employmentFieldGroup.classList.add('show');

        // Focus on employment field after animation
        setTimeout(() => {
            document.getElementById('employmentStatus').focus();
        }, 400);
    }
}

// Progressive disclosure for Step 2 (employment -> household)
function showHouseholdField() {
    const employmentStatus = document.getElementById('employmentStatus').value;
    const householdFieldGroup = document.getElementById('householdFieldGroup');

    if (employmentStatus && householdFieldGroup.classList.contains('hidden')) {
        householdFieldGroup.classList.remove('hidden');
        householdFieldGroup.classList.add('show');

        // Focus on household field after animation
        setTimeout(() => {
            document.getElementById('householdStatus').focus();
        }, 400);
    }
}

// Update account balance fields based on selected accounts in Step 4
function updateAccountBalanceFields() {
    const selectedAccounts = Array.from(document.querySelectorAll('input[name="accounts"]:checked'))
        .map(checkbox => checkbox.value);

    // Hide all registered account balance fields first
    document.getElementById('tfsaBalanceGroup').classList.add('hidden');
    document.getElementById('rrspBalanceGroup').classList.add('hidden');
    document.getElementById('respBalanceGroup').classList.add('hidden');
    document.getElementById('fhsaBalanceGroup').classList.add('hidden');

    // Show only the selected account balance fields
    selectedAccounts.forEach(account => {
        if (account === 'tfsa') {
            document.getElementById('tfsaBalanceGroup').classList.remove('hidden');
        } else if (account === 'rrsp') {
            document.getElementById('rrspBalanceGroup').classList.remove('hidden');
        } else if (account === 'resp') {
            document.getElementById('respBalanceGroup').classList.remove('hidden');
        } else if (account === 'fhsa') {
            document.getElementById('fhsaBalanceGroup').classList.remove('hidden');
        }
    });
}

// Progressive disclosure for Step 7 (email -> password)
function showPasswordFields() {
    const email = document.getElementById('email').value.trim();
    const passwordFieldsGroup = document.getElementById('passwordFieldsGroup');

    if (email && isValidEmail(email) && passwordFieldsGroup.classList.contains('hidden')) {
        passwordFieldsGroup.classList.remove('hidden');
        passwordFieldsGroup.classList.add('show');

        // Focus on password field after animation
        setTimeout(() => {
            document.getElementById('password').focus();
        }, 400);
    }
}


// Questionnaire helper: build a date string from month/day/year fields
function buildDateString(monthId, dayId, yearId) {
    const month = document.getElementById(monthId).value;
    const day = document.getElementById(dayId).value;
    const year = document.getElementById(yearId).value;
    if (!month || !day || !year) return null;
    return `${year}-${String(month).padStart(2, '0')}-${String(day).padStart(2, '0')}`;
}

// Holdings setup
let holdingRowCount = 0;
let searchTimeouts = {};

function addHoldingRow() {
    const container = document.getElementById('holdingsRows');
    const index = holdingRowCount++;
    const row = document.createElement('div');
    row.className = 'holding-row';
    row.dataset.index = index;
    row.innerHTML = `
        <div class="form-group">
            <label>Ticker</label>
            <div class="ticker-autocomplete-signup">
                <input type="text" class="holding-ticker-input" data-index="${index}" placeholder="Search..." autocomplete="off">
                <input type="hidden" class="holding-ticker-symbol" data-index="${index}">
                <input type="hidden" class="holding-ticker-name" data-index="${index}">
                <div class="ticker-dropdown-signup" id="tickerDropdown-${index}"></div>
            </div>
        </div>
        <div class="form-group">
            <label>Shares</label>
            <input type="number" class="holding-shares" data-index="${index}" step="0.0001" min="0" placeholder="0">
        </div>
        <div class="form-group">
            <label>Avg Cost ($)</label>
            <input type="number" class="holding-avg-cost" data-index="${index}" step="0.01" min="0" placeholder="0.00">
        </div>
        <button type="button" class="btn-remove-holding" onclick="this.closest('.holding-row').remove()">
            <i class="fas fa-times"></i>
        </button>
    `;
    container.appendChild(row);
    initHoldingTickerSearch(index);
}

function initHoldingTickerSearch(index) {
    const input = document.querySelector(`.holding-ticker-input[data-index="${index}"]`);
    const dropdown = document.getElementById(`tickerDropdown-${index}`);
    const hiddenSymbol = document.querySelector(`.holding-ticker-symbol[data-index="${index}"]`);
    const hiddenName = document.querySelector(`.holding-ticker-name[data-index="${index}"]`);

    input.addEventListener('input', function() {
        const query = this.value.trim();
        clearTimeout(searchTimeouts[index]);

        if (query.length < 1) {
            dropdown.classList.remove('active');
            hiddenSymbol.value = '';
            hiddenName.value = '';
            return;
        }

        searchTimeouts[index] = setTimeout(async () => {
            try {
                const response = await fetch(`/api/tickers/search?q=${encodeURIComponent(query)}`);
                const data = await response.json();
                renderTickerDropdown(dropdown, data.tickers || [], input, hiddenSymbol, hiddenName);
            } catch (e) {
                dropdown.classList.remove('active');
            }
        }, 300);
    });

    input.addEventListener('blur', function() {
        setTimeout(() => dropdown.classList.remove('active'), 200);
    });
}

function renderTickerDropdown(dropdown, tickers, input, hiddenSymbol, hiddenName) {
    if (!tickers.length) {
        dropdown.classList.remove('active');
        return;
    }

    dropdown.innerHTML = tickers.slice(0, 8).map(t => `
        <div class="ticker-item" data-symbol="${t.symbol}" data-name="${t.name}">
            <span class="ticker-symbol">${t.symbol}</span>
            <span class="ticker-name">${t.name}</span>
        </div>
    `).join('');

    dropdown.querySelectorAll('.ticker-item').forEach(item => {
        item.addEventListener('mousedown', function(e) {
            e.preventDefault();
            const symbol = this.dataset.symbol;
            const name = this.dataset.name;
            input.value = `${symbol} - ${name}`;
            hiddenSymbol.value = symbol;
            hiddenName.value = name;
            dropdown.classList.remove('active');
        });
    });

    dropdown.classList.add('active');
}

function collectHoldings() {
    const holdings = [];
    document.querySelectorAll('.holding-row').forEach(row => {
        const idx = row.dataset.index;
        const ticker = row.querySelector(`.holding-ticker-symbol[data-index="${idx}"]`).value;
        const name = row.querySelector(`.holding-ticker-name[data-index="${idx}"]`).value;
        const shares = parseFloat(row.querySelector(`.holding-shares[data-index="${idx}"]`).value) || 0;
        const avgCost = parseFloat(row.querySelector(`.holding-avg-cost[data-index="${idx}"]`).value) || 0;

        if (ticker && shares > 0 && avgCost > 0) {
            holdings.push({ ticker, name, shares, avgCost });
        }
    });
    return holdings;
}

// Questionnaire functions
function showQuestionnaire(hasTfsa, hasFhsa, tfsaBalance) {
    const overlay = document.getElementById('questionnaireOverlay');
    overlay.classList.remove('hidden');

    // Show holdings section if TFSA has contributions
    if (hasTfsa && tfsaBalance > 0) {
        document.getElementById('qHoldings').style.display = '';
        addHoldingRow();
    }

    // Add holding row button
    document.getElementById('addHoldingRow').addEventListener('click', addHoldingRow);

    // Toggle residency date field based on radio selection
    document.querySelectorAll('input[name="residentBefore18"]').forEach(radio => {
        radio.addEventListener('change', function() {
            const dateGroup = document.getElementById('residencyDateGroup');
            if (this.value === 'no') {
                dateGroup.style.display = '';
                document.getElementById('qResMonth').required = true;
                document.getElementById('qResDay').required = true;
                document.getElementById('qResYear').required = true;
            } else {
                dateGroup.style.display = 'none';
                document.getElementById('qResMonth').required = false;
                document.getElementById('qResDay').required = false;
                document.getElementById('qResYear').required = false;
                document.getElementById('qResMonth').value = '';
                document.getElementById('qResDay').value = '';
                document.getElementById('qResYear').value = '';
            }
        });
    });
}

async function submitQuestionnaire() {
    const data = {
        dateOfBirth: buildDateString('qDobMonth', 'qDobDay', 'qDobYear'),
        residentBefore18: document.querySelector('input[name="residentBefore18"]:checked')?.value === 'yes'
    };

    const residencyDate = buildDateString('qResMonth', 'qResDay', 'qResYear');
    if (residencyDate) {
        data.residencyDate = residencyDate;
    }

    // Collect holdings
    const holdings = collectHoldings();
    if (holdings.length > 0) {
        data.holdings = holdings;
    }

    try {
        const response = await fetch('/api/account-questionnaire', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data)
        });

        const result = await response.json();

        if (result.error) {
            throw new Error(result.error);
        }

        window.location.href = '/';
    } catch (error) {
        console.error('Questionnaire error:', error);
        alert('Error saving details: ' + error.message);
    }
}

// Initialize
document.addEventListener('DOMContentLoaded', function() {
    console.log('Signup page loaded');

    // Add event listeners to all budget inputs
    const budgetInputs = document.querySelectorAll('[name^="budget"]');
    budgetInputs.forEach(input => {
        input.addEventListener('input', updateTotalBudget);
    });

    // Initialize total
    updateTotalBudget();

    // Progressive disclosure for Step 1 - full name field
    const fullNameInput = document.getElementById('fullName');
    if (fullNameInput) {
        fullNameInput.addEventListener('input', showProvinceField);
        fullNameInput.addEventListener('blur', showProvinceField);
    }

    // Progressive disclosure for Step 2 - life stage field
    const lifeStageInput = document.getElementById('lifeStage');
    if (lifeStageInput) {
        lifeStageInput.addEventListener('change', showEmploymentField);
    }

    // Progressive disclosure for Step 2 - employment status field
    const employmentStatusInput = document.getElementById('employmentStatus');
    if (employmentStatusInput) {
        employmentStatusInput.addEventListener('change', showHouseholdField);
    }

    // Progressive disclosure for Step 7 - email field
    const emailInput = document.getElementById('email');
    if (emailInput) {
        emailInput.addEventListener('input', showPasswordFields);
        emailInput.addEventListener('blur', showPasswordFields);
    }

    // Add password visibility toggle functionality (hold to view)
    const toggleButtons = document.querySelectorAll('.toggle-password');
    toggleButtons.forEach(button => {
        const targetId = button.getAttribute('data-target');

        // Mouse events
        button.addEventListener('mousedown', function(e) {
            e.preventDefault();
            showPassword(targetId);
        });

        button.addEventListener('mouseup', function(e) {
            e.preventDefault();
            hidePassword(targetId);
        });

        button.addEventListener('mouseleave', function() {
            hidePassword(targetId);
        });

        // Touch events for mobile
        button.addEventListener('touchstart', function(e) {
            e.preventDefault();
            showPassword(targetId);
        });

        button.addEventListener('touchend', function(e) {
            e.preventDefault();
            hidePassword(targetId);
        });
    });

    // Questionnaire form handlers
    const questionnaireForm = document.getElementById('questionnaireForm');
    if (questionnaireForm) {
        questionnaireForm.addEventListener('submit', function(e) {
            e.preventDefault();
            submitQuestionnaire();
        });
    }

    const skipBtn = document.getElementById('skipQuestionnaire');
    if (skipBtn) {
        skipBtn.addEventListener('click', function() {
            window.location.href = '/';
        });
    }
});

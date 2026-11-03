// Shared auth JS for login, forgot-password and reset-password pages.
// Each handler only wires itself up if its form is present on the page.

function showLoading(message) {
    const overlay = document.getElementById('loadingOverlay');
    if (!overlay) return;
    const p = overlay.querySelector('p');
    if (p && message) p.textContent = message;
    overlay.classList.remove('hidden');
}
function hideLoading() {
    const overlay = document.getElementById('loadingOverlay');
    if (overlay) overlay.classList.add('hidden');
}

// ── Login ───────────────────────────────────────────────────────────────

const loginForm = document.getElementById('loginForm');
if (loginForm) {
    loginForm.addEventListener('submit', async function (e) {
        e.preventDefault();
        const errEl = document.getElementById('loginError');
        errEl.classList.add('hidden');
        showLoading('Signing in...');

        try {
            const response = await fetch('/api/login', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    email: document.getElementById('email').value.trim(),
                    password: document.getElementById('password').value,
                }),
            });
            const data = await response.json();
            if (data.error) throw new Error(data.error);
            window.location.href = '/dashboard';
        } catch (error) {
            errEl.textContent = error.message;
            errEl.classList.remove('hidden');
        } finally {
            hideLoading();
        }
    });
}

// ── Forgot password ────────────────────────────────────────────────────

const forgotForm = document.getElementById('forgotForm');
if (forgotForm) {
    forgotForm.addEventListener('submit', async function (e) {
        e.preventDefault();
        const errEl = document.getElementById('forgotError');
        const successEl = document.getElementById('forgotSuccess');
        errEl.classList.add('hidden');
        successEl.classList.add('hidden');

        try {
            const response = await fetch('/api/forgot-password', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ email: document.getElementById('email').value.trim() }),
            });
            const data = await response.json();
            if (data.error) throw new Error(data.error);
            successEl.textContent = data.message || 'If that email has an account, a reset link has been sent.';
            successEl.classList.remove('hidden');
            forgotForm.reset();
        } catch (error) {
            errEl.textContent = error.message;
            errEl.classList.remove('hidden');
        }
    });
}

// ── Reset password ─────────────────────────────────────────────────────

const resetForm = document.getElementById('resetForm');
if (resetForm) {
    resetForm.addEventListener('submit', async function (e) {
        e.preventDefault();
        const errEl = document.getElementById('resetError');
        errEl.classList.add('hidden');

        const password = document.getElementById('password').value;
        const confirmPassword = document.getElementById('confirmPassword').value;
        if (password !== confirmPassword) {
            errEl.textContent = 'Passwords do not match.';
            errEl.classList.remove('hidden');
            return;
        }

        try {
            const response = await fetch('/api/reset-password', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ token: resetForm.dataset.token, password }),
            });
            const data = await response.json();
            if (data.error) throw new Error(data.error);
            window.location.href = '/login';
        } catch (error) {
            errEl.textContent = error.message;
            errEl.classList.remove('hidden');
        }
    });
}

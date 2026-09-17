// Form submission
document.getElementById('loginForm').addEventListener('submit', async function(e) {
    e.preventDefault();

    // Show loading overlay
    document.getElementById('loadingOverlay').classList.remove('hidden');

    // Collect form data
    const formData = {
        email: document.getElementById('email').value.trim(),
        password: document.getElementById('password').value
    };

    try {
        const response = await fetch('/api/login', {
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

        // Success! Redirect to dashboard
        window.location.href = '/';
    } catch (error) {
        console.error('Login error:', error);
        alert('Error signing in: ' + error.message);
    } finally {
        document.getElementById('loadingOverlay').classList.add('hidden');
    }
});

// Initialize
document.addEventListener('DOMContentLoaded', function() {
    console.log('Login page loaded');
});

// ── Forgot Password ──────────────────────────────────────────────────────────

function openResetModal() {
    document.getElementById('resetModal').classList.remove('hidden');
    document.getElementById('resetEmail').focus();
}

function closeResetModal() {
    document.getElementById('resetModal').classList.add('hidden');
    document.getElementById('resetEmail').value = '';
    document.getElementById('resetNewPassword').value = '';
    document.getElementById('resetConfirmPassword').value = '';
    document.getElementById('resetError').classList.add('hidden');
}

async function submitReset() {
    const email    = document.getElementById('resetEmail').value.trim();
    const password = document.getElementById('resetNewPassword').value;
    const confirm  = document.getElementById('resetConfirmPassword').value;
    const errEl    = document.getElementById('resetError');

    errEl.classList.add('hidden');

    if (!email || !password || !confirm) {
        errEl.textContent = 'Please fill in all fields.';
        errEl.classList.remove('hidden');
        return;
    }
    if (password !== confirm) {
        errEl.textContent = 'Passwords do not match.';
        errEl.classList.remove('hidden');
        return;
    }
    if (password.length < 6) {
        errEl.textContent = 'Password must be at least 6 characters.';
        errEl.classList.remove('hidden');
        return;
    }

    try {
        const res = await fetch('/api/reset-password', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ email, password })
        });
        const data = await res.json();
        if (data.error) throw new Error(data.error);

        closeResetModal();
        alert('Password reset successfully. You can now sign in.');
    } catch (err) {
        errEl.textContent = err.message;
        errEl.classList.remove('hidden');
    }
}

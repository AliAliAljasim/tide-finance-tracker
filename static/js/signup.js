document.getElementById('signupForm').addEventListener('submit', async function (e) {
    e.preventDefault();
    const errEl = document.getElementById('signupError');
    errEl.classList.add('hidden');

    const email = document.getElementById('email').value.trim();
    const password = document.getElementById('password').value;
    const confirmPassword = document.getElementById('confirmPassword').value;

    if (password !== confirmPassword) {
        errEl.textContent = 'Passwords do not match.';
        errEl.classList.remove('hidden');
        return;
    }
    if (password.length < 8) {
        errEl.textContent = 'Password must be at least 8 characters.';
        errEl.classList.remove('hidden');
        return;
    }

    document.getElementById('loadingOverlay').classList.remove('hidden');
    try {
        const response = await fetch('/api/signup', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ email, password }),
        });
        const data = await response.json();
        if (data.error) throw new Error(data.error);
        window.location.href = '/upload';
    } catch (error) {
        errEl.textContent = error.message;
        errEl.classList.remove('hidden');
    } finally {
        document.getElementById('loadingOverlay').classList.add('hidden');
    }
});

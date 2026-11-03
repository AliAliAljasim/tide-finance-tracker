// US-17: in-app alerts when a category reaches 80% and 100% of its budget.
// Loaded on every signed-in page. Shows a strip under the header plus a count
// on the Budgets nav link. Dismissing hides an alert for this browser session
// only, and only at its current level, so crossing 100% after dismissing the
// 80% alert shows again.

(function () {
    const strip = document.getElementById('budgetAlertStrip');
    const badge = document.getElementById('budgetNavBadge');
    if (!strip || !badge) return;
    const DISMISS_KEY = 'budgetAlertsDismissed';

    function readDismissed() {
        try { return JSON.parse(sessionStorage.getItem(DISMISS_KEY) || '[]'); } catch (e) { return []; }
    }
    function writeDismissed(list) {
        try { sessionStorage.setItem(DISMISS_KEY, JSON.stringify(list)); } catch (e) { /* storage blocked: dismiss lasts this page only */ }
    }
    function alertKey(month, a) { return `${month}:${a.category_id}:${a.level}`; }
    function escapeHtml(str) {
        const div = document.createElement('div');
        div.textContent = str == null ? '' : String(str);
        return div.innerHTML;
    }

    function render(month, alerts) {
        badge.textContent = alerts.length;
        badge.className = 'nav-badge' + (alerts.length ? '' : ' hidden') + (alerts.some(a => a.level === 'over') ? '' : ' warning');

        // The Budgets page lists these itself.
        const dismissed = readDismissed();
        const visible = location.pathname === '/budgets' ? [] : alerts.filter(a => !dismissed.includes(alertKey(month, a)));
        if (!visible.length) {
            strip.classList.add('hidden');
            return;
        }
        strip.innerHTML = visible.map(a => `
            <div class="alert-item ${a.level}">
                <span>${escapeHtml(a.message)}</span>
                <a href="/budgets" class="link">View budgets</a>
                <button type="button" class="alert-dismiss" data-key="${escapeHtml(alertKey(month, a))}" aria-label="Dismiss">&times;</button>
            </div>`).join('');
        strip.classList.remove('hidden');
        strip.querySelectorAll('.alert-dismiss').forEach(btn => btn.addEventListener('click', () => {
            writeDismissed([...readDismissed(), btn.dataset.key]);
            render(month, alerts);
        }));
    }

    async function load() {
        try {
            const res = await fetch('/api/budgets');
            if (!res.ok) return;
            const data = await res.json();
            render(data.month, data.alerts || []);
        } catch (e) { /* alerts are best-effort; the page works without them */ }
    }

    window.refreshBudgetAlerts = load;
    load();
})();

// App shell: collapsible sidebar and the user menu (theme, hide amounts,
// name, password). Loaded on every signed-in page.

(function () {
    const root = document.documentElement;

    function toast(message, isError) {
        const el = document.getElementById('shellToast');
        el.textContent = message;
        el.className = 'toast ' + (isError ? 'error' : 'success');
        clearTimeout(el._t);
        el._t = setTimeout(() => el.classList.add('hidden'), 3000);
    }

    async function api(url, method, body) {
        const res = await fetch(url, { method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
        const data = await res.json().catch(() => ({}));
        if (!res.ok || data.error) throw new Error(data.error || 'Something went wrong. Please try again.');
        return data;
    }

    // ── Sidebar ─────────────────────────────────────────────────────────

    const toggle = document.getElementById('sideToggle');
    const sidebar = document.getElementById('sidebar');
    const content = document.querySelector('.app-content');

    function syncToggle() {
        const collapsed = root.classList.contains('sidebar-collapsed');
        toggle.setAttribute('aria-expanded', String(!collapsed));
        const label = collapsed ? 'Expand sidebar' : 'Collapse sidebar';
        toggle.setAttribute('aria-label', label);
        toggle.title = label;
        toggle.querySelector('i').className = collapsed ? 'icon-panel-left-open' : 'icon-panel-left-close';
    }

    toggle.addEventListener('click', () => {
        // Pin the content to its current width while the sidebar slides, then
        // let it settle once at the end: cards move as one piece instead of
        // re-wrapping on every frame.
        content.style.width = content.getBoundingClientRect().width + 'px';
        const collapsed = root.classList.toggle('sidebar-collapsed');
        try { localStorage.setItem('finance-sidebar', collapsed ? 'collapsed' : 'expanded'); } catch (e) { /* ignore */ }
        syncToggle();
        const release = e => {
            if (e && e.target !== sidebar) return;
            sidebar.removeEventListener('transitionend', release);
            content.style.width = '';
            // Charts size themselves on resize.
            window.dispatchEvent(new Event('resize'));
        };
        sidebar.addEventListener('transitionend', release);
        setTimeout(release, 400);  // reduced motion / no transition fired
    });

    syncToggle();
    // Enable the slide only after first paint, so a saved collapsed state doesn't animate in.
    requestAnimationFrame(() => requestAnimationFrame(() => root.classList.add('sidebar-ready')));

    // ── User menu ───────────────────────────────────────────────────────

    const btn = document.getElementById('userMenuBtn');
    const menu = document.getElementById('userMenu');
    const items = () => [...menu.querySelectorAll('.theme-switch button, .menu-item')];

    function place() {
        const r = btn.getBoundingClientRect();
        const m = menu.getBoundingClientRect();
        const gap = 8;
        let top, left;
        if (r.top > window.innerHeight / 2) {
            // Bottom of the sidebar: open upward, or to the side when the rail is collapsed.
            if (root.classList.contains('sidebar-collapsed') && window.innerWidth > 900) {
                left = r.right + gap;
                top = r.bottom - m.height;
            } else {
                left = r.left;
                top = r.top - m.height - gap;
            }
        } else {
            // Phone top bar: drop down, right-aligned to the avatar.
            left = r.right - m.width;
            top = r.bottom + gap;
        }
        menu.style.left = Math.max(12, Math.min(left, window.innerWidth - m.width - 12)) + 'px';
        menu.style.top = Math.max(12, top) + 'px';
    }

    function openMenu() {
        menu.hidden = false;
        btn.setAttribute('aria-expanded', 'true');
        place();
        (menu.querySelector('.theme-switch [aria-checked="true"]') || items()[0]).focus();
    }

    function closeMenu(returnFocus) {
        if (menu.hidden) return;
        menu.hidden = true;
        btn.setAttribute('aria-expanded', 'false');
        if (returnFocus) btn.focus();
    }

    btn.addEventListener('click', () => (menu.hidden ? openMenu() : closeMenu(true)));
    document.addEventListener('click', e => {
        if (!menu.hidden && !menu.contains(e.target) && !btn.contains(e.target)) closeMenu(false);
    });
    window.addEventListener('resize', () => { if (!menu.hidden) place(); });
    menu.addEventListener('keydown', e => {
        if (e.key === 'Escape') return closeMenu(true);
        if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
            e.preventDefault();
            const list = items();
            const i = list.indexOf(document.activeElement);
            list[(i + (e.key === 'ArrowDown' ? 1 : -1) + list.length) % list.length].focus();
        }
    });

    // Theme: applied instantly, then saved to the account.
    menu.querySelectorAll('[data-theme-choice]').forEach(b => b.addEventListener('click', async () => {
        const theme = b.dataset.themeChoice;
        const previous = root.getAttribute('data-theme') || 'system';
        const apply = t => {
            if (t === 'system') root.removeAttribute('data-theme'); else root.setAttribute('data-theme', t);
            menu.querySelectorAll('[data-theme-choice]').forEach(x => x.setAttribute('aria-checked', String(x.dataset.themeChoice === t)));
        };
        apply(theme);
        try {
            await api('/api/preferences', 'PUT', { theme });
        } catch (err) {
            apply(previous);
            toast(err.message, true);
        }
    }));

    const hideToggle = document.getElementById('hideAmountsToggle');
    hideToggle.addEventListener('click', async () => {
        const on = hideToggle.getAttribute('aria-checked') !== 'true';
        const apply = v => { root.classList.toggle('hide-amounts', v); hideToggle.setAttribute('aria-checked', String(v)); };
        apply(on);
        try {
            await api('/api/preferences', 'PUT', { hide_amounts: on });
        } catch (err) {
            apply(!on);
            toast(err.message, true);
        }
    });

    // ── Hide amounts: mark every dollar figure in running text ─────────
    // Pages build their own text ("$1,500.00 in withdrawals returns…"), so
    // rather than tagging each template, wrap anything that looks like money
    // in <span class="amt">, including content rendered later. CSS only
    // redacts .amt while the hide-amounts class is on, so toggling is instant.

    const MONEY_RE = /[−+-]?\$\d[\d,]*(?:\.\d+)?[KM]?/g;
    const SKIP = 'script, style, textarea, .amt, .money, .stat-value, .user-menu';

    function markAmounts(rootNode) {
        const walker = document.createTreeWalker(rootNode, NodeFilter.SHOW_TEXT, {
            acceptNode: n => (n.nodeValue.includes('$') && n.parentElement && !n.parentElement.closest(SKIP)
                ? NodeFilter.FILTER_ACCEPT : NodeFilter.FILTER_REJECT),
        });
        const nodes = [];
        while (walker.nextNode()) nodes.push(walker.currentNode);
        nodes.forEach(node => {
            const parent = node.parentElement;
            // SVG <text> can't hold an HTML span; tag the label itself.
            if (parent.closest('svg')) {
                if (MONEY_RE.test(node.nodeValue)) parent.classList.add('amt');
                MONEY_RE.lastIndex = 0;
                return;
            }
            const text = node.nodeValue;
            const frag = document.createDocumentFragment();
            let last = 0;
            for (const m of text.matchAll(MONEY_RE)) {
                if (m.index > last) frag.append(text.slice(last, m.index));
                const span = document.createElement('span');
                span.className = 'amt';
                span.textContent = m[0];
                frag.append(span);
                last = m.index + m[0].length;
            }
            if (!last) return;
            if (last < text.length) frag.append(text.slice(last));
            node.replaceWith(frag);
        });
    }

    markAmounts(document.body);
    new MutationObserver(records => {
        records.forEach(r => r.addedNodes.forEach(n => {
            if (n.nodeType === Node.ELEMENT_NODE) markAmounts(n);
            else if (n.nodeType === Node.TEXT_NODE && n.parentElement) markAmounts(n.parentElement);
        }));
    }).observe(document.body, { childList: true, subtree: true });

    // ── Dialogs: edit name, change password ────────────────────────────

    function openDialog(id) {
        closeMenu(false);
        const d = document.getElementById(id);
        d.querySelectorAll('.form-error').forEach(e => e.classList.add('hidden'));
        d.classList.add('show');
        const first = d.querySelector('input');
        if (first) { first.focus(); first.select(); }
    }

    function closeDialog(d) {
        d.classList.remove('show');
        btn.focus();
    }

    menu.querySelectorAll('[data-open-dialog]').forEach(b => b.addEventListener('click', () => openDialog(b.dataset.openDialog)));
    ['profileDialog', 'passwordDialog'].forEach(id => {
        const d = document.getElementById(id);
        d.querySelectorAll('[data-close-dialog]').forEach(b => b.addEventListener('click', () => closeDialog(d)));
        d.addEventListener('keydown', e => { if (e.key === 'Escape') closeDialog(d); });
    });

    function showFormError(id, message) {
        const el = document.getElementById(id);
        el.textContent = message;
        el.classList.remove('hidden');
    }

    document.getElementById('profileForm').addEventListener('submit', async e => {
        e.preventDefault();
        try {
            await api('/api/profile', 'PUT', { name: document.getElementById('profileName').value });
            location.reload();  // name appears in the sidebar, menu and greeting
        } catch (err) {
            showFormError('profileError', err.message);
        }
    });

    document.getElementById('passwordForm').addEventListener('submit', async e => {
        e.preventDefault();
        const current = document.getElementById('currentPassword');
        const next = document.getElementById('newPassword');
        const confirm = document.getElementById('confirmNewPassword');
        if (next.value !== confirm.value) return showFormError('passwordError', 'The new passwords don’t match.');
        try {
            await api('/api/change-password', 'POST', { current_password: current.value, new_password: next.value });
            e.target.reset();
            closeDialog(document.getElementById('passwordDialog'));
            toast('Password updated.', false);
        } catch (err) {
            showFormError('passwordError', err.message);
        }
    });
})();

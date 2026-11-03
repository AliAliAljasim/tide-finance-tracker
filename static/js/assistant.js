// AI assistant panel, on every signed-in page. The conversation is kept in
// sessionStorage so it follows you between pages until the tab closes.
// The server only ever *proposes* adding an account; it's created here, via
// the normal accounts API, when the user clicks the confirm button.

(function () {
    const STORE_KEY = 'finance-assistant';
    const fab = document.getElementById('assistFab');
    const panel = document.getElementById('assistPanel');
    if (!fab || !panel) return;
    const thread = document.getElementById('assistThread');
    const empty = document.getElementById('assistEmpty');
    const body = document.getElementById('assistBody');
    const form = document.getElementById('assistForm');
    const input = document.getElementById('assistInput');
    const send = document.getElementById('assistSend');
    const newBtn = document.getElementById('assistNew');

    // { messages: [{role, content, proposal?, proposalState?}], open: bool }
    let state = load();
    let busy = false;
    let slow = false;  // the local model can take a while on CPU; say so
    let slowTimer = null;

    function load() {
        try {
            const s = JSON.parse(sessionStorage.getItem(STORE_KEY));
            if (s && Array.isArray(s.messages)) return s;
        } catch (e) { /* storage blocked or corrupt: start fresh */ }
        return { messages: [], open: false };
    }

    function save() {
        try { sessionStorage.setItem(STORE_KEY, JSON.stringify(state)); } catch (e) { /* ignore */ }
    }

    function esc(str) {
        const div = document.createElement('div');
        div.textContent = str == null ? '' : String(str);
        return div.innerHTML;
    }

    function fmtMoney(n) {
        const v = Number(n || 0);
        return (v < 0 ? '−$' : '$') + Math.abs(v).toLocaleString('en-CA', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    }

    // Plain text from the model → escaped HTML with **bold**, `code` and "- " lists.
    function formatReply(text) {
        const inline = s => esc(s).replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>').replace(/`([^`]+)`/g, '<code>$1</code>');
        const out = [];
        let list = [];
        const flush = () => { if (list.length) { out.push(`<ul>${list.join('')}</ul>`); list = []; } };
        text.split('\n').forEach(line => {
            const t = line.trim();
            if (/^[-*•]\s+/.test(t)) list.push(`<li>${inline(t.replace(/^[-*•]\s+/, ''))}</li>`);
            else { flush(); if (t) out.push(`<p>${inline(t)}</p>`); }
        });
        flush();
        return out.join('');
    }

    function proposalHtml(p, idx, msgState) {
        const s = p.summary;
        const rows = [['Type', s.type_label], s.institution ? ['Institution', s.institution] : null,
            s.amount_label ? [s.amount_label, fmtMoney(s.amount)] : null].filter(Boolean);
        let foot;
        if (msgState === 'added') foot = `<p class="assist-action-done">Added. <a href="${esc(s.view_url)}">View it</a></p>`;
        else if (msgState === 'dismissed') foot = '<p class="assist-action-done muted">Not added.</p>';
        else foot = `
            <div class="assist-action-buttons">
                <button type="button" class="btn btn-primary btn-sm" data-confirm="${idx}"><i class="icon-plus"></i>Add account</button>
                <button type="button" class="btn btn-ghost btn-sm" data-dismiss="${idx}">Not now</button>
            </div>
            <p class="form-error hidden" data-error="${idx}"></p>`;
        return `
        <div class="assist-action">
            <div class="assist-action-head">
                <span class="row-icon" aria-hidden="true"><i class="icon-${p.endpoint === '/api/registered' ? 'trending-up' : 'landmark'}"></i></span>
                <strong>${esc(s.title)}</strong>
            </div>
            <dl>${rows.map(([k, v]) => `<dt>${esc(k)}</dt><dd>${esc(v)}</dd>`).join('')}</dl>
            ${foot}
        </div>`;
    }

    function render() {
        empty.classList.toggle('hidden', state.messages.length > 0);
        newBtn.classList.toggle('hidden', state.messages.length === 0);
        thread.innerHTML = state.messages.map((m, i) => {
            if (m.role === 'user') return `<div class="assist-msg user">${esc(m.content)}</div>`;
            return `<div class="assist-msg bot${m.error ? ' error' : ''}">${formatReply(m.content)}${m.proposal ? proposalHtml(m.proposal, i, m.proposalState) : ''}</div>`;
        }).join('') + (busy ? `<div class="assist-msg bot" aria-label="Assistant is typing"><span class="assist-typing"><span></span><span></span><span></span></span>${slow ? '<p class="assist-slow">Still thinking. The AI runs on this computer, so it can take up to a minute.</p>' : ''}</div>` : '');
        body.scrollTop = body.scrollHeight;
    }

    function setOpen(open) {
        state.open = open;
        save();
        panel.hidden = !open;
        fab.setAttribute('aria-expanded', String(open));
        if (open) {
            render();
            input.focus();
        } else {
            fab.focus();
        }
    }

    async function ask(text) {
        if (busy || !text.trim()) return;
        state.messages.push({ role: 'user', content: text.trim() });
        busy = true;
        slow = false;
        slowTimer = setTimeout(() => { slow = true; render(); }, 8000);
        input.value = '';
        syncSend();
        save();
        render();
        try {
            // Errors and proposals are display-only; the model just sees the text.
            const history = state.messages.filter(m => !m.error).map(m => ({ role: m.role, content: m.content }));
            const res = await fetch('/api/assistant', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ messages: history }),
            });
            const data = await res.json().catch(() => ({}));
            if (!res.ok || data.error) throw new Error(data.error || 'The assistant couldn’t answer right now.');
            state.messages.push({ role: 'assistant', content: data.reply, proposal: data.proposal || null });
        } catch (err) {
            state.messages.push({ role: 'assistant', content: err.message, error: true });
        } finally {
            busy = false;
            clearTimeout(slowTimer);
            save();
            render();
            input.focus();
        }
    }

    async function confirmProposal(idx, btn) {
        const msg = state.messages[idx];
        if (!msg || !msg.proposal) return;
        btn.disabled = true;
        const errEl = thread.querySelector(`[data-error="${idx}"]`);
        try {
            const res = await fetch(msg.proposal.endpoint, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(msg.proposal.payload),
            });
            const data = await res.json().catch(() => ({}));
            if (!res.ok || data.error) throw new Error(data.error || 'Couldn’t add the account.');
            msg.proposalState = 'added';
            save();
            render();
            // Pages showing accounts pick up the new one.
            if (['/dashboard', '/accounts', '/investing'].includes(location.pathname)) setTimeout(() => location.reload(), 900);
        } catch (err) {
            btn.disabled = false;
            if (errEl) { errEl.textContent = err.message; errEl.classList.remove('hidden'); }
        }
    }

    function syncSend() {
        send.disabled = busy || !input.value.trim();
    }

    fab.addEventListener('click', () => setOpen(true));
    document.getElementById('assistClose').addEventListener('click', () => setOpen(false));
    newBtn.addEventListener('click', () => {
        if (busy) return;
        state.messages = [];
        save();
        render();
        input.focus();
    });
    panel.addEventListener('keydown', e => { if (e.key === 'Escape') setOpen(false); });
    form.addEventListener('submit', e => { e.preventDefault(); ask(input.value); });
    input.addEventListener('input', syncSend);
    input.addEventListener('keydown', e => {
        if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) {
            e.preventDefault();
            ask(input.value);
        }
    });
    empty.addEventListener('click', e => {
        const chip = e.target.closest('[data-ask]');
        if (chip) ask(chip.dataset.ask);
    });
    thread.addEventListener('click', e => {
        const c = e.target.closest('[data-confirm]');
        if (c) return confirmProposal(Number(c.dataset.confirm), c);
        const d = e.target.closest('[data-dismiss]');
        if (d) {
            state.messages[Number(d.dataset.dismiss)].proposalState = 'dismissed';
            save();
            render();
        }
    });

    if (state.open) setOpen(true);
})();

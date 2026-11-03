// Month picker: upgrades <input type="month" data-month-picker> into
// "‹ November 2026 ›" with a calendar of months (year header + 12-month
// grid; no days). The original input stays in the page, hidden, and keeps
// its value as YYYY-MM and fires `change`, so page scripts don't change.
// data-max="current" disables months after this one.

(function () {
    const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

    function key(y, m) { return `${y}-${String(m + 1).padStart(2, '0')}`; }
    function parse(v) {
        const match = /^(\d{4})-(\d{2})$/.exec(v || '');
        return match ? { y: +match[1], m: +match[2] - 1 } : null;
    }
    function label(v) {
        const p = parse(v);
        return p ? new Date(p.y, p.m, 1).toLocaleDateString('en-CA', { month: 'long', year: 'numeric' }) : 'Choose a month';
    }

    function upgrade(input) {
        const now = new Date();
        const current = key(now.getFullYear(), now.getMonth());
        const max = input.dataset.max === 'current' ? current : null;
        const allowed = v => !max || v <= max;

        const wrap = document.createElement('div');
        wrap.className = 'month-picker';
        wrap.innerHTML = `
            <button type="button" class="icon-btn icon-btn-sm mp-step" data-step="-1" aria-label="Previous month"><i class="icon-chevron-left"></i></button>
            <button type="button" class="mp-trigger" aria-haspopup="dialog" aria-expanded="false"><i class="icon-calendar" aria-hidden="true"></i><span></span></button>
            <button type="button" class="icon-btn icon-btn-sm mp-step" data-step="1" aria-label="Next month"><i class="icon-chevron-right"></i></button>
            <div class="mp-pop" role="dialog" aria-label="Choose a month" hidden>
                <div class="mp-head">
                    <button type="button" class="icon-btn icon-btn-sm" data-year="-1" aria-label="Previous year"><i class="icon-chevron-left"></i></button>
                    <strong class="mp-year"></strong>
                    <button type="button" class="icon-btn icon-btn-sm" data-year="1" aria-label="Next year"><i class="icon-chevron-right"></i></button>
                </div>
                <div class="mp-grid" role="grid"></div>
                <div class="mp-foot"><button type="button" class="link mp-today">This month</button></div>
            </div>`;
        input.after(wrap);
        input.classList.add('visually-hidden');
        input.tabIndex = -1;
        input.setAttribute('aria-hidden', 'true');
        // The field's <label> now names the trigger button.
        const fieldLabel = input.closest('label');
        if (fieldLabel) {
            const text = fieldLabel.querySelector('span');
            wrap.querySelector('.mp-trigger').setAttribute('aria-label', `${text ? text.textContent : 'Month'}: ${label(input.value)}`);
            fieldLabel.addEventListener('click', e => { if (!wrap.contains(e.target)) e.preventDefault(); });
        }

        const trigger = wrap.querySelector('.mp-trigger');
        const pop = wrap.querySelector('.mp-pop');
        const grid = wrap.querySelector('.mp-grid');
        let viewYear = now.getFullYear();

        function syncLabel() {
            trigger.querySelector('span').textContent = label(input.value);
            if (fieldLabel) trigger.setAttribute('aria-label', `${fieldLabel.querySelector('span')?.textContent || 'Month'}: ${label(input.value)}`);
            const p = parse(input.value);
            const next = p ? (p.m === 11 ? key(p.y + 1, 0) : key(p.y, p.m + 1)) : null;
            wrap.querySelector('[data-step="1"]').disabled = !p || !allowed(next);
        }

        function renderGrid(focusMonth) {
            wrap.querySelector('.mp-year').textContent = viewYear;
            wrap.querySelector('[data-year="1"]').disabled = !!max && viewYear >= +max.slice(0, 4);
            grid.innerHTML = MONTHS.map((name, m) => {
                const v = key(viewYear, m);
                const cls = ['mp-month', v === input.value ? 'selected' : '', v === current ? 'current' : ''].filter(Boolean).join(' ');
                return `<button type="button" class="${cls}" data-value="${v}" role="gridcell"
                    aria-selected="${v === input.value}" ${allowed(v) ? '' : 'disabled'}
                    aria-label="${new Date(viewYear, m, 1).toLocaleDateString('en-CA', { month: 'long', year: 'numeric' })}">${name}</button>`;
            }).join('');
            if (focusMonth != null) {
                const btns = [...grid.children];
                (btns[focusMonth] && !btns[focusMonth].disabled ? btns[focusMonth] : btns.find(b => !b.disabled) || btns[0]).focus();
            }
        }

        function choose(v) {
            if (!allowed(v)) return;
            input.value = v;
            input.dispatchEvent(new Event('change', { bubbles: true }));
            syncLabel();
        }

        function open() {
            const p = parse(input.value) || { y: now.getFullYear(), m: now.getMonth() };
            viewYear = p.y;
            pop.hidden = false;
            // Anchored to the right edge; flip to the left edge if that would overflow (narrow screens).
            pop.style.left = pop.style.right = '';
            if (pop.getBoundingClientRect().left < 8) { pop.style.left = '0'; pop.style.right = 'auto'; }
            trigger.setAttribute('aria-expanded', 'true');
            renderGrid(p.m);
        }

        function close(focusTrigger) {
            if (pop.hidden) return;
            pop.hidden = true;
            trigger.setAttribute('aria-expanded', 'false');
            if (focusTrigger) trigger.focus();
        }

        trigger.addEventListener('click', () => (pop.hidden ? open() : close(true)));
        wrap.querySelectorAll('.mp-step').forEach(b => b.addEventListener('click', () => {
            const p = parse(input.value) || { y: now.getFullYear(), m: now.getMonth() };
            const d = new Date(p.y, p.m + Number(b.dataset.step), 1);
            choose(key(d.getFullYear(), d.getMonth()));
        }));
        wrap.querySelectorAll('[data-year]').forEach(b => b.addEventListener('click', () => {
            viewYear += Number(b.dataset.year);
            renderGrid();
        }));
        grid.addEventListener('click', e => {
            const b = e.target.closest('.mp-month');
            if (b && !b.disabled) { choose(b.dataset.value); close(true); }
        });
        wrap.querySelector('.mp-today').addEventListener('click', () => { choose(current); close(true); });

        pop.addEventListener('keydown', e => {
            if (e.key === 'Escape') { e.preventDefault(); return close(true); }
            const btns = [...grid.children];
            const i = btns.indexOf(document.activeElement);
            if (i < 0) return;
            const moves = { ArrowLeft: -1, ArrowRight: 1, ArrowUp: -3, ArrowDown: 3 };
            if (e.key in moves) {
                e.preventDefault();
                let n = i + moves[e.key];
                if (n < 0) { viewYear -= 1; renderGrid(n + 12); return; }
                if (n > 11) { viewYear += 1; renderGrid(n - 12); return; }
                btns[n].focus();
            } else if (e.key === 'PageUp' || e.key === 'PageDown') {
                e.preventDefault();
                viewYear += e.key === 'PageUp' ? -1 : 1;
                renderGrid(i);
            }
        });
        document.addEventListener('click', e => { if (!wrap.contains(e.target)) close(false); });
        input.addEventListener('change', syncLabel);

        syncLabel();
    }

    // Page scripts set the initial value before this runs.
    document.addEventListener('DOMContentLoaded', () => {
        document.querySelectorAll('input[type="month"][data-month-picker]').forEach(upgrade);
    });
})();

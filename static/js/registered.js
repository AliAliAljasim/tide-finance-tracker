// Investing: every investment/savings account, grouped by how it's limited
// (yearly room, lifetime cap, or none). Type rules come from /api/registered.

let types = [];

function escapeHtml(str) {
    const div = document.createElement('div');
    div.textContent = str == null ? '' : String(str);
    return div.innerHTML;
}

function money(n) {
    const v = Number(n || 0);
    return (v < 0 ? '−$' : '$') + Math.abs(v).toLocaleString('en-CA', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function showToast(message, isError) {
    const toast = document.getElementById('toast');
    toast.textContent = message;
    toast.className = 'toast ' + (isError ? 'error' : 'success');
    setTimeout(() => toast.classList.add('hidden'), 3000);
}

function bar(pct, tone) {
    return `<div class="bar"><span class="${tone}" style="width:${Math.max(0, Math.min(pct, 100))}%;"></span></div>`;
}

function barCaption(left, right) {
    return `<div class="tabular invest-caption"><span>${left}</span><span>${right}</span></div>`;
}

// Kind-specific body under the headline figure.
function cardDetail(a) {
    const cur = a.current;
    if (a.kind === 'none') {
        return `<p class="invest-note">${a.type === 'non_registered'
            ? 'No contribution limits. Growth and income here are taxable.'
            : a.type === 'lira'
                ? 'Locked in: money comes in by transfer from a pension and generally can’t be withdrawn early.'
                : 'Minimum withdrawals each year; no new contributions.'}</p>`;
    }
    if (a.kind === 'lifetime') {
        const pct = cur.lifetime_contributed / a.lifetime_limit * 100;
        let html = bar(pct, cur.lifetime_remaining < 0 ? 'over' : 'accent')
            + barCaption(`${money(cur.lifetime_contributed)} contributed`, `of ${money(a.lifetime_limit)} lifetime`);
        if (a.type === 'resp') {
            html += `
                <div class="invest-sub-meter">
                    <div class="mini-row-head"><strong>${cur.year} grant</strong><span>${money(cur.grant_earned)} CESG</span></div>
                    ${bar(cur.grant_eligible / 2500 * 100, 'ok')}
                    ${barCaption(`${money(cur.grant_eligible)} of $2,500`, cur.grant_room_left > 0 ? `${money(cur.grant_room_left)} more for the full 20%` : 'Full grant earned')}
                </div>`;
        }
        return html;
    }
    const usedPct = cur.room > 0 ? cur.contributed / cur.room * 100 : (cur.contributed > 0 ? 100 : 0);
    let html = bar(usedPct, cur.available < 0 ? 'over' : 'accent')
        + barCaption(`${money(cur.contributed)} contributed`, `of ${money(cur.room)} room on Jan 1`);
    if (a.type === 'fhsa') {
        html += `<div class="invest-sub-meter">${bar(cur.lifetime_contributed / a.lifetime_limit * 100, cur.lifetime_remaining < 0 ? 'over' : 'quiet')}
            ${barCaption(`Lifetime: ${money(cur.lifetime_contributed)}`, 'of $40,000')}</div>`;
    } else if (a.type === 'tfsa' && cur.restored_next_year > 0) {
        html += `<p class="invest-note">${money(cur.restored_next_year)} in withdrawals returns to your room on January 1, ${cur.year + 1}.</p>`;
    } else if (a.type === 'rrsp') {
        html += `<p class="invest-note">${a.annual_room > 0 ? `${money(a.annual_room)} of new room on January 1, ${cur.year + 1}. ` : ''}CRA allows a $2,000 cushion before the penalty tax.</p>`;
    }
    return html;
}

function accountCard(a) {
    const h = investHeadline(a);
    const meta = [a.type_name, a.institution].filter(Boolean).map(escapeHtml).join(' · ');
    const inLabel = a.kind === 'none' ? 'Log deposit' : 'Log contribution';
    return `
    <div class="card card-lg invest-card">
        <div class="invest-card-head">
            <span class="row-icon" aria-hidden="true"><i class="icon-${investIcon(a.type)}"></i></span>
            <span class="row-main">
                <a href="/investing/${a._id}" class="row-title">${escapeHtml(a.name)}</a>
                <span class="row-meta">${meta}</span>
            </span>
            ${investBadge(a)}
            <button type="button" class="btn btn-ghost btn-sm edit-registered" data-id="${a._id}">Edit</button>
        </div>
        <div class="label">${escapeHtml(h.label)}</div>
        <div class="money money-xl ${h.over ? 'neg' : ''}" style="display:block;margin:8px 0 16px;">${moneyHtml(h.value)}</div>
        ${cardDetail(a)}
        <div class="invest-actions">
            <a href="/investing/${a._id}?log=contribution" class="btn btn-outline btn-sm"><i class="icon-plus"></i>${inLabel}</a>
            <a href="/investing/${a._id}?log=withdrawal" class="btn btn-outline btn-sm"><i class="icon-minus"></i>Log withdrawal</a>
        </div>
    </div>`;
}

function renderSummary(accounts, year) {
    const contributed = accounts.reduce((s, a) => s + (a.current.contributed || 0), 0);
    const roomAccounts = accounts.filter(a => a.kind === 'annual');
    const room = roomAccounts.reduce((s, a) => s + Math.max(a.current.available, 0), 0);
    document.getElementById('sumContribLabel').textContent = `Contributed in ${year}`;
    document.getElementById('sumContrib').innerHTML = moneyHtml(contributed);
    document.getElementById('sumRoom').innerHTML = roomAccounts.length ? moneyHtml(room) : '&mdash;';
    document.getElementById('sumRoomSub').textContent = roomAccounts.length
        ? `Across ${roomAccounts.map(a => a.label).filter((l, i, all) => all.indexOf(l) === i).join(', ')}`
        : 'Add a TFSA, FHSA or RRSP to track room';
    document.getElementById('sumCount').textContent = accounts.length;
    const labels = accounts.map(a => a.label).filter((l, i, all) => all.indexOf(l) === i);
    document.getElementById('sumCountSub').textContent = labels.join(', ');
}

async function loadRegistered() {
    const res = await fetch('/api/registered');
    const data = await res.json();
    types = data.types || [];
    const grid = document.getElementById('registeredGrid');
    const accounts = data.accounts || [];
    document.getElementById('registeredEmpty').classList.toggle('hidden', accounts.length > 0);
    document.getElementById('addRegisteredBtn').classList.toggle('hidden', accounts.length === 0);
    document.getElementById('investSummary').classList.toggle('hidden', accounts.length === 0);
    if (accounts.length === 0) {
        grid.innerHTML = '';
        return;
    }
    renderSummary(accounts, data.year);
    grid.innerHTML = INVEST_KIND_GROUPS.map(g => {
        const group = accounts.filter(a => a.kind === g.kind);
        if (!group.length) return '';
        return `
        <section class="invest-group">
            <div class="invest-group-head"><h2 class="section-title">${g.title}</h2><span class="muted">${g.blurb}</span></div>
            <div class="grid-cards">${group.map(accountCard).join('')}</div>
        </section>`;
    }).join('');

    grid.querySelectorAll('.edit-registered').forEach(btn => btn.addEventListener('click', () => openEditModal(accounts.find(a => a._id === btn.dataset.id))));
}

// ── Add / edit modal ───────────────────────────────────────────────────

const modal = document.getElementById('registeredModal');
const form = document.getElementById('registeredForm');
const typeSelect = document.getElementById('registeredType');

function typeMeta(type) {
    return types.find(t => t.type === type) || {};
}

function fillTypeOptions() {
    typeSelect.innerHTML = INVEST_KIND_GROUPS.map(g => `
        <optgroup label="${g.title}">
            ${types.filter(t => t.kind === g.kind).map(t => `<option value="${t.type}">${escapeHtml(t.label === t.name ? t.name : `${t.label} (${t.name})`)}</option>`).join('')}
        </optgroup>`).join('');
}

function syncTypeFields() {
    const type = typeSelect.value;
    const meta = typeMeta(type);
    const ui = INVEST_TYPES[type] || {};
    const annual = meta.kind === 'annual';
    const usesPrior = type === 'fhsa' || meta.kind === 'lifetime';

    document.getElementById('startingRoomField').classList.toggle('hidden', !annual);
    document.getElementById('registeredStartingRoom').required = annual;
    document.getElementById('startYearLabel').textContent = annual ? 'As of Jan 1,' : 'Tracking since';
    document.getElementById('startYearField').style.flex = annual ? '0 0 120px' : '';
    document.getElementById('startingRoomLabel').textContent = type === 'rrsp' ? 'Deduction limit' : 'Starting room';
    document.getElementById('startingRoomHelp').textContent = annual
        ? ui.roomHelp
        : 'The year you want to start logging from. Entries can’t be dated earlier.';
    document.getElementById('annualRoomField').classList.toggle('hidden', type !== 'rrsp');
    document.getElementById('priorContributionsField').classList.toggle('hidden', !usesPrior);
    document.getElementById('priorContributionsLabel').textContent = `${meta.label} contributions made before that year`;
    document.getElementById('priorContributionsHint').textContent = ui.priorHint || '';
    document.getElementById('registeredName').placeholder = ui.placeholder || '';
    document.getElementById('registeredModalDesc').textContent = annual
        ? 'Use the contribution room shown in CRA My Account. We’ll keep it current as you log activity.'
        : meta.kind === 'lifetime'
            ? `${meta.label}s have no yearly room, just a ${money(meta.lifetime_limit).replace('.00', '')} lifetime limit. We’ll warn you before you go over.`
            : 'No contribution limits to track. Log money in and out to keep a running total.';
    const year = document.getElementById('registeredStartYear');
    year.min = meta.first_year;
    year.max = new Date().getFullYear();
}

function openAddModal() {
    form.reset();
    fillTypeOptions();
    document.getElementById('registeredModalTitle').textContent = 'Add account';
    document.getElementById('registeredId').value = '';
    document.getElementById('registeredStartYear').value = new Date().getFullYear();
    typeSelect.disabled = false;
    document.getElementById('registeredFormError').classList.add('hidden');
    syncTypeFields();
    modal.classList.add('show');
}

function openEditModal(a) {
    if (!a) return;
    fillTypeOptions();
    document.getElementById('registeredModalTitle').textContent = `Edit ${a.label}`;
    document.getElementById('registeredId').value = a._id;
    typeSelect.value = a.type;
    typeSelect.disabled = true;
    document.getElementById('registeredName').value = a.name;
    document.getElementById('registeredInstitution').value = a.institution || '';
    document.getElementById('registeredStartingRoom').value = a.starting_room;
    document.getElementById('registeredStartYear').value = a.start_year;
    document.getElementById('registeredPriorContributions').value = a.prior_contributions || 0;
    document.getElementById('registeredAnnualRoom').value = a.annual_room || 0;
    document.getElementById('registeredFormError').classList.add('hidden');
    syncTypeFields();
    modal.classList.add('show');
}

function closeModal() { modal.classList.remove('show'); }

typeSelect.addEventListener('change', syncTypeFields);
document.getElementById('addRegisteredBtn').addEventListener('click', openAddModal);
document.getElementById('addRegisteredEmptyBtn').addEventListener('click', openAddModal);
document.getElementById('registeredModalClose').addEventListener('click', closeModal);
document.getElementById('registeredModalCancel').addEventListener('click', closeModal);

form.addEventListener('submit', async function (e) {
    e.preventDefault();
    const errEl = document.getElementById('registeredFormError');
    errEl.classList.add('hidden');
    const id = document.getElementById('registeredId').value;
    const payload = {
        type: typeSelect.value,
        name: document.getElementById('registeredName').value.trim(),
        institution: document.getElementById('registeredInstitution').value.trim(),
        starting_room: document.getElementById('registeredStartingRoom').value || 0,
        start_year: document.getElementById('registeredStartYear').value,
        prior_contributions: document.getElementById('registeredPriorContributions').value || 0,
        annual_room: document.getElementById('registeredAnnualRoom').value || 0,
    };
    const res = await fetch(id ? `/api/registered/${id}` : '/api/registered', {
        method: id ? 'PUT' : 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
    });
    const data = await res.json();
    if (data.error) {
        errEl.textContent = data.error;
        errEl.classList.remove('hidden');
        return;
    }
    closeModal();
    showToast(id ? 'Account updated.' : 'Account added.', false);
    loadRegistered();
});

loadRegistered();

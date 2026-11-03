// Presentation for each investing account type: icon, badge tone and copy.
// The rules themselves (kinds, limits, first years) come from the server
// (registered.py), so only display details live here.

const INVEST_TYPES = {
    tfsa: { icon: 'piggy-bank', badge: 'badge-accent', placeholder: 'e.g. Riverside TFSA',
        roomHelp: 'Your unused TFSA room on Jan 1 of that year, as shown in CRA My Account. It already includes that year\'s new limit.' },
    fhsa: { icon: 'house', badge: 'badge-info', placeholder: 'e.g. First home FHSA',
        roomHelp: 'Your FHSA participation room for that year from CRA My Account: $8,000, plus up to $8,000 carried forward.',
        priorHint: 'Counts toward the $40,000 lifetime limit.' },
    rrsp: { icon: 'sunset', badge: 'badge-positive', placeholder: 'e.g. Workplace RRSP',
        roomHelp: 'Your RRSP deduction limit for that year, from your latest Notice of Assessment or CRA My Account.' },
    resp: { icon: 'graduation-cap', badge: 'badge-warning', placeholder: 'e.g. Sam’s RESP',
        priorHint: 'Counts toward the $50,000 lifetime limit per beneficiary.' },
    rdsp: { icon: 'heart-handshake', badge: 'badge-info', placeholder: 'e.g. Family RDSP',
        priorHint: 'Counts toward the $200,000 lifetime limit.' },
    lira: { icon: 'lock', badge: '', placeholder: 'e.g. Pension LIRA' },
    rrif: { icon: 'hourglass', badge: '', placeholder: 'e.g. Retirement RRIF' },
    non_registered: { icon: 'chart-candlestick', badge: '', placeholder: 'e.g. Brokerage or high-interest savings' },
};

const INVEST_KIND_GROUPS = [
    { kind: 'annual', title: 'Yearly contribution room', blurb: 'New room every January 1.' },
    { kind: 'lifetime', title: 'Lifetime limits', blurb: 'No yearly room, one cap on everything ever contributed.' },
    { kind: 'none', title: 'No contribution limits', blurb: 'A record of money in and out.' },
];

function investIcon(type) {
    return (INVEST_TYPES[type] || {}).icon || 'wallet';
}

function investBadge(account) {
    const tone = (INVEST_TYPES[account.type] || {}).badge || '';
    return `<span class="badge ${tone}">${escapeHtml(account.label)}</span>`;
}

// One-line status used on cards and the dashboard: what's left, or what's in.
function investHeadline(a) {
    const cur = a.current;
    if (a.kind === 'none') {
        return { label: 'Net deposited', value: cur.total_net, over: false, sub: `${money(cur.contributed)} in, ${money(cur.withdrawn)} out in ${cur.year}` };
    }
    const over = cur.available < 0;
    if (a.kind === 'lifetime') {
        return { label: over ? 'Over the lifetime limit' : 'Lifetime room left', value: Math.abs(cur.available), over,
            sub: `${money(cur.lifetime_contributed)} contributed of ${money(a.lifetime_limit)}` };
    }
    return { label: over ? `Over-contributed in ${cur.year}` : `Room left in ${cur.year}`, value: Math.abs(cur.available), over,
        sub: `${money(cur.contributed)} contributed of ${money(cur.room)} room on Jan 1` };
}

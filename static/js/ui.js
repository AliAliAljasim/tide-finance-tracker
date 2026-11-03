// Shared display helpers for the design system's Money and category-icon
// patterns. Loaded on every signed-in page before the page's own script.

// Serif money figure with the cents at half size: −$1,184.62 → −$1,184<small>.62</small>.
// signed=true prefixes positive amounts with "+".
function moneyHtml(n, signed) {
    const v = Number(n || 0);
    const prefix = v < 0 ? '−' : (signed && v > 0 ? '+' : '');
    const [whole, cents] = Math.abs(v).toLocaleString('en-CA', { minimumFractionDigits: 2, maximumFractionDigits: 2 }).split('.');
    return `${prefix}$${whole}<span class="cents">.${cents}</span>`;
}

const CATEGORY_ICONS = {
    'Groceries': 'shopping-basket', 'Dining': 'utensils', 'Rent / Mortgage': 'house', 'Utilities': 'zap',
    'Transportation': 'car', 'Shopping': 'shopping-bag', 'Entertainment': 'film', 'Health': 'heart-pulse',
    'Subscriptions': 'repeat', 'Fees & interest': 'receipt', 'Transfers': 'arrow-left-right',
};

function categoryIconHtml(name, isIncome) {
    const icon = isIncome ? 'arrow-down-left' : (CATEGORY_ICONS[name] || 'circle');
    return `<span class="cat-icon${isIncome ? ' income' : ''}" aria-hidden="true"><i class="icon-${icon}"></i></span>`;
}

# Personal Finance Tracking App
## Sprint 2 — Coding Tasks

**Sprint 2:** Oct 12 – Oct 25 (demo at the Week 6 lab, Oct 19 week)
**Module:** Accounts, income & expense tracking
**Builds on:** Sprint 1 (auth, statement upload, AI parsing, review & save)

---

## Stories in This Sprint

| # | ID | Story | Priority | Pts | Owner |
| --- | --- | --- | --- | --- | --- |
| 1 | US-09 | Create chequing, savings and credit card accounts | Must | 3 | [Name] |
| 2 | US-10 | Link each statement to an account | Must | 3 | [Name] |
| 3 | US-11 | Auto-categorize transactions | Must | 5 | [Name] |
| 4 | US-13 | Monthly income vs. expense summary | Must | 5 | [Name] |
| 5 | US-08 | Detect duplicate transactions | Should | 5 | [Name] |
| 6 | US-12 | Remember category changes | Should | 3 | [Name] |
| 7 | US-14 | Spending-by-category chart | Should | 3 | [Name] |
| | | **Total** | | **27** | |

**Before starting:** finish any Sprint 1 stories that carried over. They come first.

---

## 1. Database Changes

### New tables

| Table | Fields |
| --- | --- |
| `categories` | id, name, kind (`income` / `expense`), is_default |
| `merchant_rules` | id, user_id, merchant_key, category_id, updated_at |

### Changes to existing tables

| Table | Add |
| --- | --- |
| `accounts` | institution, opening_balance, current_balance, created_at |
| `transactions` | category_id, is_duplicate (bool), merchant_key |

### Tasks

- [ ] Write migration for `categories` and seed default categories
- [ ] Write migration for `merchant_rules`
- [ ] Add new columns to `accounts` and `transactions`
- [ ] Add indexes on `transactions(account_id, date)` and `merchant_rules(user_id, merchant_key)`

### Default categories (seed data)

- **Income:** Salary, Freelance / Side income, Investment income, Refund, Other income
- **Expense:** Groceries, Dining, Rent / Mortgage, Utilities, Transportation, Shopping, Entertainment, Health, Subscriptions, Fees & interest, Transfers, Other

---

## 2. Accounts (US-09)

- [ ] **API:** create, list, edit, delete accounts for the logged-in user only
- [ ] **Fields:** name, type (`chequing` / `savings` / `credit_card`), institution, opening balance
- [ ] **Validation:** name required; type must be one of the three; balance is a number
- [ ] **UI:** "Add account" form
- [ ] **UI:** account list on the home screen showing name, type and current balance
- [ ] Block deleting an account that has transactions (or ask the user to confirm)

**Done when:** an account is saved with name, type and institution and appears on the home screen.

---

## 3. Link Statements to Accounts (US-10)

- [ ] Make account selection **required** on the upload screen (dropdown of the user's accounts)
- [ ] Save `account_id` on the statement and on every confirmed transaction
- [ ] Recalculate `current_balance` after transactions are saved
  - Chequing / savings: opening balance + credits − debits
  - Credit card: balance owed = opening balance + charges − payments
- [ ] Show transactions per account on an account detail page

**Done when:** a statement is linked to the chosen account and that account's balance updates after save.

---

## 4. Auto-Categorization (US-11)

Run after the user confirms parsed transactions:

1. Normalize the description into a `merchant_key` (lowercase, strip numbers and store IDs, e.g. `"GROCERY STORE #123"` → `"grocery store"`)
2. If the user has a `merchant_rules` entry for that key, use it
3. Else, apply simple keyword rules (e.g. `payroll` → Salary, `netflix` → Subscriptions)
4. Else, batch the remaining transactions to the LLM with the category list and ask for one category per row (JSON)
5. Credits default to income categories, debits to expense categories

### Tasks

- [ ] `normalizeMerchant(description)` function
- [ ] Keyword rules table/file
- [ ] LLM categorization call with fixed prompt and JSON response
- [ ] Fallback to "Other" if the AI call fails, never block saving
- [ ] Show category on each transaction row

**Done when:** every transaction gets a category, and 85%+ are correct on the test set.

---

## 5. Remember Category Changes (US-12)

- [ ] Category dropdown on each transaction row (editable)
- [ ] On change: update the transaction **and** upsert a `merchant_rules` row for that user + merchant key
- [ ] Optional: ask "Apply to all past transactions from this merchant?"
- [ ] Next import checks `merchant_rules` first (step 2 above)

**Done when:** after changing a category, the same merchant gets the new category on the next import.

---

## 6. Duplicate Detection (US-08)

- [ ] Before saving, compare each new transaction to existing ones in the same account
- [ ] Match rule: same date, same amount, and same `merchant_key`
- [ ] Mark matches as `is_duplicate = true` and highlight them on the review screen
- [ ] User chooses **Keep** or **Skip** for each flagged row
- [ ] Skipped rows are not saved

**Done when:** uploading two overlapping statements does not double-count any transaction.

---

## 7. Monthly Income vs. Expense Summary (US-13)

- [ ] **API:** `GET /summary/monthly?from=YYYY-MM&to=YYYY-MM&account=all|<id>`
  - Returns per month: total income, total expenses, net (income − expenses)
  - Excludes `Transfers` category so moving money between accounts isn't counted twice
- [ ] **UI:** grouped bar chart (income vs. expenses per month)
- [ ] **UI:** summary cards for the current month: income, expenses, net
- [ ] Filter by account

**Done when:** monthly totals match the saved transactions and the bar chart displays them.

---

## 8. Spending by Category Chart (US-14)

- [ ] **API:** `GET /summary/categories?month=YYYY-MM&account=all|<id>`
  - Returns total spent per expense category for that month
- [ ] **UI:** bar chart (or donut) of spending per category, largest first
- [ ] Month picker and account filter
- [ ] Clicking a category lists its transactions

**Done when:** the chart shows spending per category for the selected month and can be filtered by account.

---

## 9. Testing

### Unit tests

- [ ] Account create/edit validation
- [ ] Balance recalculation (chequing and credit card)
- [ ] `normalizeMerchant()` on sample descriptions
- [ ] Merchant rule overrides keyword and AI categories
- [ ] Duplicate match rule (match / no match cases)
- [ ] Monthly totals and category totals, including Transfers excluded

### Integration / acceptance tests

- [ ] Upload a statement → linked account balance updates
- [ ] Upload two overlapping statements → duplicates flagged, none double-counted
- [ ] Change a category → next import uses it
- [ ] Charts match totals calculated by hand for one synthetic month

### Accuracy test

- [ ] Label 50–100 synthetic transactions with the correct category
- [ ] Run categorization and record % correct (target 85%+)

---

## 10. Definition of Done (each story)

- [ ] Acceptance criteria met and accepted by the Product Owner
- [ ] Code reviewed by another team member and merged
- [ ] Unit tests written and passing; no known critical bugs
- [ ] Works on phone and desktop screen widths
- [ ] No real personal financial data used in tests or demos

---

## Suggested Order

1. Database migrations and seed categories
2. Accounts API + UI (US-09)
3. Link statements to accounts + balance update (US-10)
4. Categorization pipeline (US-11)
5. Duplicate detection (US-08)
6. Category editing + merchant rules (US-12)
7. Summary APIs and charts (US-13, US-14)
8. Testing and accuracy run

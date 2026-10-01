# Personal Finance Tracking App
## Week 3 — Sprint 1 (Start): Requirements

**Week of:** Sep 28, 2026
**Sprint 1:** Sep 28 – Oct 11 (ends at the Week 4 lab)
**Sprint goal:** A user can create an account, upload a bank statement, and get back AI-parsed transactions they can review and save.

---

## This Week's Deliverables (Lab Presentation)

| Deliverable | What to show |
| --- | --- |
| Sprint backlog | The 7 stories pulled into Sprint 1, with points, owner and status |
| Implementation plan | Tech stack, architecture, and how the parsing pipeline will work |
| Scrum meeting points | Notes from this week's Scrum meeting (done / next / blockers) |

---

## Sprint Planning

- [ ] Pull the top-priority stories from the product backlog into the Sprint 1 backlog
- [ ] Confirm the sprint goal with the Product Owner
- [ ] Break each story into tasks and assign an owner to each
- [ ] Check total points (29) against team capacity
- [ ] Agree on the tech stack and repository setup
- [ ] Set up the board (To Do / In Progress / Testing / Done) and the burndown chart
- [ ] Hold the first weekly Scrum meeting and record the points

---

## Sprint 1 Backlog

| # | ID | User Story | Priority | Pts | Owner | Status |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | US-01 | As a new user, I want to register with email and password so that my data is private to me | Must | 3 | [Name] | To Do |
| 2 | US-02 | As a user, I want to log in and out securely so that no one else sees my finances | Must | 3 | [Name] | To Do |
| 3 | US-04 | As a user, I want to upload a PDF or image statement so that I don't retype transactions | Must | 5 | [Name] | To Do |
| 4 | US-05 | As a user, I want AI to extract transactions from a PDF statement so that they are captured automatically | Must | 8 | [Name] | To Do |
| 5 | US-06 | As a user, I want photos or scans of statements read with OCR so that paper statements work too | Must | 3 | [Name] | To Do |
| 6 | US-07 | As a user, I want to review and edit parsed transactions before saving so that errors are fixed | Must | 5 | [Name] | To Do |
| 7 | US-03 | As a user, I want to reset a forgotten password so that I can regain access | Should | 2 | [Name] | To Do |
| | | **Total** | | **29** | | |

---

## Coding Requirements

### 1. User Account Setup (US-01, US-02, US-03)

- Registration with email and password
  - Valid email format required; duplicate emails rejected
  - Password at least 8 characters, stored hashed (bcrypt or Argon2), never in plain text
- Login and logout with secure sessions
  - Wrong credentials show a clear error message
  - Session expires after 30 minutes of inactivity
- Password reset by emailed link that expires after 1 hour
- All pages served over HTTPS

### 2. Statement Upload (US-04)

- Accept PDF, JPG and PNG files up to 10 MB
- Reject any other file type or size with a clear message
- User selects which account the statement belongs to (a simple account name/type is enough for Sprint 1; full account features come in Sprint 2)

### 3. AI Parsing Pipeline (US-05, US-06)

1. Read text from the PDF's text layer
2. Run OCR on scanned PDFs and images
3. Mask account numbers before sending text to the AI service
4. Send the text to an LLM with a fixed prompt and JSON schema
5. Receive one record per transaction:

   | Field | Type | Example |
   | --- | --- | --- |
   | date | date (YYYY-MM-DD) | 2026-09-14 |
   | description | text | GROCERY STORE #123 |
   | amount | decimal | 54.20 |
   | type | debit / credit | debit |
   | balance | decimal (if on statement) | 1,245.80 |

6. Validate the result
   - Opening balance + transactions = closing balance
   - Every date falls inside the statement period
   - Rows that fail are flagged for the user
7. If parsing fails, save nothing and show a retry message

### 4. Review & Save (US-07)

- Show parsed transactions in an editable table
- User can edit, delete or add rows
- Flagged rows are highlighted
- Nothing is saved until the user clicks **Confirm**
- On confirm: save transactions to the database and delete the uploaded file

### 5. Data Model (minimum for Sprint 1)

| Table | Key fields |
| --- | --- |
| users | id, email, password_hash, created_at |
| accounts | id, user_id, name, type |
| statements | id, account_id, period_start, period_end, status |
| transactions | id, account_id, statement_id, date, description, amount, type, balance |

---

## Non-Functional Requirements (Sprint 1)

| Area | Requirement |
| --- | --- |
| Security | Hashed passwords, HTTPS, data encrypted at rest |
| Privacy | Uploaded files deleted after parsing; account numbers masked; no real financial data in testing |
| Accuracy | 95%+ field-level extraction accuracy on the test statement set |
| Performance | A 3-page statement parsed in under 30 seconds |
| Reliability | A failed parse never saves partial data |

---

## Testing Requirements

- [ ] Unit tests for registration, login and password validation
- [ ] Unit tests for upload file-type and size checks
- [ ] Unit tests for balance and date validation
- [ ] Create 3–4 **synthetic** statements in different bank layouts (no real customer data)
- [ ] Run the parser on each and record field-level accuracy
- [ ] Test the failure path: a bad file shows an error and saves nothing

---

## Definition of Done

- [ ] Acceptance criteria met and accepted by the Product Owner
- [ ] Code reviewed by another team member and merged
- [ ] Unit tests written and passing; no known critical bugs
- [ ] No real personal financial data used in tests or demos
- [ ] Documentation updated

---

## Looking Ahead: Week 4 (Sprint 1 End)

The Week 4 lab expects:

- A working demo of the **statement upload & AI parsing module**
- Implementation, test results and charts (burndown, test results)
- Sprint Review and **retrospective report**
- Scrum meeting points

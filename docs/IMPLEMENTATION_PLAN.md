# Sprint 1 Implementation Plan

## Tech stack

| Layer | Choice | Why |
| --- | --- | --- |
| Backend | Flask 3 (`app.py`) | Already the project's framework; session-based auth, server-rendered pages + JSON API. |
| Data store | `firestore_db.py` — a local JSON-file-backed stand-in for the Firestore client API | Carried over from the existing app; keeps `user_ref`/`sub`/`stream_docs`-style code portable to real Firestore later if needed. Nested as `users/{uid}/{accounts,statements,transactions}`. |
| Auth | `bcrypt` password hashing, Flask sessions, `itsdangerous` signed tokens for password reset | Spec requires bcrypt/Argon2 (not plain Werkzeug `generate_password_hash`), and a reset link that expires after exactly 1 hour — `itsdangerous.URLSafeTimedSerializer(max_age=...)` gives that for free without a separate tokens table. |
| PDF/text extraction | `pdfplumber` | Reads a PDF's embedded text layer directly; already in the venv. |
| OCR | `pytesseract` (+ Pillow) | Standard Python wrapper around the `tesseract` OCR engine for scanned PDFs/images. **Not installed as a system binary in this dev environment** — see Risks. |
| AI extraction | Anthropic API, forced tool-use with a JSON schema | Matches "send the text to an LLM with a fixed prompt and JSON schema, one record per transaction." |
| Testing | `pytest` | Only testing tool the stack needs for unit tests; no existing test setup to conform to. |

## Architecture

```
Browser (upload.html / review.html)
        |  fetch() JSON + multipart
        v
Flask routes (app.py)
  /api/upload  ----> parsing.py pipeline ----> instance/uploads/<uid>/<statement_id>.<ext>
        |                                               |
        |                                      deleted on confirm/failure
        v
firestore_db.py (instance/local_db.json)
  users/{uid}/accounts
  users/{uid}/statements
  users/{uid}/transactions
```

### Parsing pipeline (`parsing.py`), one call per upload

1. **`extract_text(path, ext)`** — PDF: `pdfplumber` reads the text layer. If a PDF has no text layer (scanned) or the file is an image, fall through to OCR (`pytesseract`). If OCR can't run, the function returns a flag (`needs_ocr_failed=True`) rather than empty text, so the caller can show a specific error.
2. **`mask_account_numbers(text)`** — regex over runs of 8+ digits (with optional spaces/dashes), replacing all but the last 4 with `X`. Runs *before* anything is sent to the AI service, per the privacy requirement.
3. **`parse_statement_text(masked_text)`** — if `ANTHROPIC_API_KEY` is set, calls `client.messages.create(..., tools=[record_transactions_schema], tool_choice={'type': 'tool', 'name': 'record_transactions'})` with a fixed prompt, forcing a structured response: `period_start`, `period_end`, `opening_balance`, `closing_balance`, and a `transactions` array of `{date, description, amount, type, balance}`. Without an API key configured, a small deterministic regex parser stands in instead, so the rest of the pipeline (and its tests) can run without API credentials — it is explicitly not the AI step and is documented as a local-only fallback in the module.
4. **`validate_transactions(...)`** — walks the transactions in the order the statement/AI returned them (not re-sorted — a statement can include a backdated entry), tracking a running balance from `opening_balance`. A row is flagged if its date falls outside `period_start`/`period_end`, or if its stated balance doesn't match the running total (tolerance $0.01). Returns the rows plus an overall `balance_ok` for the statement.
5. **App layer** (`app.py` `/api/upload`) — on any failure (`ParsingError` or an unexpected exception), the uploaded file is deleted and nothing is written to `transactions`, so a failed parse never leaves partial data. On success, one `transactions` doc is written per row and the statement is marked `parsed`.

### Review & confirm (US-07)

`/review/<statement_id>` loads the statement + its transactions and renders an editable table (`static/js/review.js`). Each row has inline inputs wired to `PUT /api/statements/<id>/transactions/<tx_id>`; "Add row" posts a blank row; "Delete" removes one. Flagged rows get a highlighted background and a tooltip with the reason. Nothing is deleted from storage until the user acts — the uploaded file itself is only deleted when the user clicks **Confirm** (`/api/statements/<id>/confirm`, which re-validates and marks the statement `confirmed`) or **Discard** (`/api/statements/<id>` `DELETE`, which removes the statement, its transactions, and the file together).

## Non-functional requirements — how each is addressed

| Requirement | Approach |
| --- | --- |
| Hashed passwords | `bcrypt.hashpw` / `bcrypt.checkpw`. |
| HTTPS | `SESSION_COOKIE_SECURE` and an optional `before_request` redirect, both gated on `FORCE_HTTPS=1` (set when deployed behind a TLS-terminating proxy; local dev has no cert to serve real HTTPS from). |
| Data encrypted at rest | Not yet implemented — the local JSON store is plaintext on disk. Flagged as a gap for a production deployment (e.g. encrypted volume, or a real Firestore/Cloud SQL instance with encryption at rest). |
| Uploaded files deleted after parsing | Deleted immediately on a failed parse; deleted on confirm (once the user has saved the reviewed data) or discard. |
| Account numbers masked | `mask_account_numbers()`, applied before the AI call. |
| No real financial data in testing | All test fixtures (`tests/fixtures/*.pdf`) are synthetic, generated by `scripts/generate_test_statements.py`. |
| A failed parse never saves partial data | `/api/upload` only writes `transactions` docs after `extract_text` → `parse_statement_text` → `validate_transactions` all succeed. |

## Risks / open items for this sprint

- **OCR has no system dependency installed.** `pytesseract` is a thin wrapper around the `tesseract-ocr` binary, which isn't present in this dev environment. Scanned PDFs/images currently fail with a clear "OCR is not available" error instead of silently returning nothing — but US-06 isn't actually demoable until `tesseract-ocr` is installed wherever this runs.
- **No email provider wired up.** Password reset tokens are generated and validated correctly, but `/api/forgot-password` logs the reset link to the console instead of sending it, since no SMTP/SES/SendGrid credentials exist yet.
- **Accuracy/performance targets (95%+ extraction accuracy, <30s for a 3-page statement) are untested against the real AI path**, since no `ANTHROPIC_API_KEY` is configured in this environment. The fallback parser used for local testing is deterministic regex matching on a fixed layout and does not represent real-world statement variety.

# Scrum Meeting Notes — Week 3 / Sprint 1 Kickoff

**Date:** _[fill in — week of Sep 28, 2026]_
**Attendees:** _[fill in]_
**Facilitator / Scrum Master:** _[fill in]_

> This file is a template for the actual Week 3 Scrum meeting — fill in the sections below with what was really discussed. The "Done" and "Blockers" bullets are pre-filled from the current state of the `sprint_1` branch so the meeting can start from facts rather than from scratch; edit or remove any that don't match what the team actually decided.

## Done this week

- Sprint 1 backlog pulled from the product backlog (`docs/SPRINT_BACKLOG.md`), 7 stories, 29 points.
- Repository scoped down to the Sprint 1 feature set (auth, upload, AI parsing, review/confirm); unrelated existing pages removed from this branch.
- Registration, login/logout, and password-reset-by-token implemented and unit tested (US-01, US-02, US-03 partial — see Blockers).
- Statement upload with file-type/size validation implemented (US-04).
- AI parsing pipeline implemented end-to-end: text extraction, account-number masking, fixed-schema LLM call (with a local fallback for offline testing), and balance/date validation (US-05, US-06 partial — see Blockers).
- Review & confirm screen implemented: editable table, flagged-row highlighting, confirm-to-save/delete-file flow (US-07).
- Synthetic test statements (3 layouts + 1 failure case) and unit tests for validation logic added.

## Next

- Install `tesseract-ocr` wherever the app is deployed/graded and confirm OCR actually runs end-to-end on a scanned statement.
- Wire up a real email provider for the password-reset link instead of the console log.
- Get an `ANTHROPIC_API_KEY` into a shared/testing environment and re-run the accuracy and performance checks (95%+ field accuracy, <30s for a 3-page statement) against the real AI path, not the local fallback parser.
- Confirm the sprint goal and point total (29) against actual team capacity; reassign story owners if this is a multi-person team.
- Start on the Week 4 deliverables: burndown chart, test-result summary, retrospective report.

## Blockers

- No OCR engine installed in the current dev environment (US-06 can't be fully demoed yet).
- No SMTP/email service connected (US-03's "emailed link" isn't actually emailed yet).
- No live Anthropic API key available in this environment to validate the AI extraction path against real, varied bank statement layouts.

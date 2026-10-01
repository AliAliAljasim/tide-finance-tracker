# Sprint 1 Backlog

**Sprint:** Sep 28 – Oct 11, 2026 (ends at the Week 4 lab)
**Sprint goal:** A user can create an account, upload a bank statement, and get back AI-parsed transactions they can review and save.

Source stories: `Week3_Sprint1_Requirements.md`. Owner defaults to the repo's git user below — reassign per story if the team splits this work up.

| # | ID | User Story | Priority | Pts | Owner | Status |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | US-01 | As a new user, I want to register with email and password so that my data is private to me | Must | 3 | AliAliAljasim | Done |
| 2 | US-02 | As a user, I want to log in and out securely so that no one else sees my finances | Must | 3 | AliAliAljasim | Done |
| 3 | US-04 | As a user, I want to upload a PDF or image statement so that I don't retype transactions | Must | 5 | AliAliAljasim | Done |
| 4 | US-05 | As a user, I want AI to extract transactions from a PDF statement so that they are captured automatically | Must | 8 | AliAliAljasim | Done (pipeline + fixed prompt/schema in place; not yet run against a real `ANTHROPIC_API_KEY`) |
| 5 | US-06 | As a user, I want photos or scans of statements read with OCR so that paper statements work too | Must | 3 | AliAliAljasim | Blocked — OCR call is wired up (`pytesseract`) but no `tesseract` binary is installed in the dev environment; fails closed with a clear error instead of silently skipping |
| 6 | US-07 | As a user, I want to review and edit parsed transactions before saving so that errors are fixed | Must | 5 | AliAliAljasim | Done |
| 7 | US-03 | As a user, I want to reset a forgotten password so that I can regain access | Should | 2 | AliAliAljasim | In Progress — token flow (1-hour expiry) is implemented and tested; no SMTP service is connected yet, so the reset link is logged to the console instead of emailed |
| | | **Total** | | **29** | | |

## Notes for sprint planning

- Check total points (29) against actual team capacity before committing to all seven stories for this sprint.
- US-06 (OCR) and the email leg of US-03 are the two items most likely to need a follow-up task: installing the `tesseract-ocr` system package wherever the app runs, and wiring up a real mail provider (SES/SendGrid/etc.).
- US-05's "95%+ field-level extraction accuracy" and "3-page statement in under 30 seconds" targets need to be measured against the real Anthropic API, not the local fallback parser — add that as an explicit task once an API key is available for testing.

---
status: partial
phase: 12-prompt-library
source: [12-VERIFICATION.md]
started: 2026-05-18T00:00:00Z
updated: 2026-05-18T00:00:00Z
---

## Current Test

[pending human browser testing]

## Tests

### 1. Fresh-install seeding (PROMPT-06)
expected: Removing settings.json and restarting shows 4 seed prompts (Generic, Apartment Search, Job Search, Candidate Search) with seed badges; no delete buttons on seeds; Generic shows active badge; main UI shows "System prompt: Generic"
result: [pending]

### 2. CRUD on user-created prompt (PROMPT-02, PROMPT-03, PROMPT-04)
expected: + Add prompt opens inline editor; name/content editable; Save persists on reload; delete button removes non-seed prompt
result: [pending]

### 3. Active prompt selection (PROMPT-05)
expected: Clicking row + Set as Active moves active badge; Save persists; active-prompt-label below task input updates reactively
result: [pending]

### 4. View prompts (PROMPT-01)
expected: All prompts listed with names visible and active one indicated in settings overlay
result: [pending]

### 5. GUARDRAIL non-exposure (PROMPT-07)
expected: /api/settings Network response body contains neither "GUARDRAIL_PROMPT" literal nor GUARDRAIL safety text; page source contains no "GUARDRAIL_PROMPT"
result: [pending]

## Summary

total: 5
passed: 0
issues: 0
pending: 5
skipped: 0
blocked: 0

## Gaps

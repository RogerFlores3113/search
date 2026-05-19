---
phase: 11-settings-panel-domain-safety
plan: "05"
subsystem: settings-panel
tags: [settings, alpine, gap-closure, security, cr-fix]
dependency_graph:
  requires: [11-01, 11-02, 11-03, 11-04]
  provides: [CR-01-fix, CR-02-fix, CR-03-fix]
  affects: [agent/templates/index.html, agent/main.py]
tech_stack:
  added: []
  patterns:
    - Alpine scope containment — settings overlay relocated inside agentUI() scope
    - Provider allow-list gate — ALLOWED_PROVIDERS set membership check before disk I/O
    - Form field round-trip — anthropic_model/openai_model persist + live-patch + UI hydration
key_files:
  modified:
    - agent/templates/index.html
    - agent/main.py
    - tests/unit/test_settings_phase11.py
decisions:
  - "Reindented overlay markup when moving inside sse-container for readability; no attribute changes"
  - "Provider gate placed BEFORE load_settings_json() call so rejection does zero disk I/O"
  - "anthropic_model/openai_model use exact fallback pattern of ollama_model (blank-preserves-existing)"
metrics:
  duration_minutes: 5
  tasks_completed: 2
  files_changed: 3
  completed_date: "2026-05-19"
---

# Phase 11 Plan 05: Gap-Closure CR-01 / CR-02 / CR-03 Summary

**One-liner:** Three surgical fixes closing the settings panel verification gaps: overlay relocated inside agentUI() Alpine scope (CR-01), provider allow-list gate with HTTP 422 (CR-02), and anthropic_model/openai_model full round-trip persistence (CR-03).

## What Was Built

### CR-01 Fix — Settings overlay relocated inside agentUI() scope

The settings overlay (`<div class="settings-overlay">`) was placed as a sibling of the disclaimer modal, inside the outer disclaimer Alpine scope. The outer scope declares only `{disclaimerAccepted, accept()}` — it has no `showSettings` property. This meant `x-show="showSettings"` always evaluated to `undefined` (falsy), rendering the overlay permanently hidden in a real browser.

**Fix:** Cut the entire overlay block from its position before the main UI shell (old lines 60-184) and pasted it as a direct child of `#sse-container` (the `agentUI()` scope), after the run-history `</section>` and before `</div><!-- /sse-container -->`. The overlay is `position:fixed` via CSS so DOM position within the scope does not affect visual placement. Zero markup changes — only DOM position changed.

### CR-02 Fix — POST /api/settings provider enum gate

The `post_settings` handler accepted any string as `provider` and persisted it without validation. A rogue or malformed POST could corrupt `settings.json` with an unsupported provider value.

**Fix:** Added `ALLOWED_PROVIDERS = {"ollama", "anthropic", "openai"}` as a module-level constant immediately above the handler. As the first statement inside the `try:` block — before any `load_settings_json()` call — added a membership check that returns `JSONResponse({"status": "error", "detail": "invalid provider"}, status_code=422)` on rejection. No disk I/O occurs on a rejected provider.

### CR-03 Fix — anthropic_model / openai_model round-trip

`anthropic_model` and `openai_model` were referenced in the overlay HTML via `x-text` (lines 118 and 134) but were:
1. Never declared in the `agentUI()` return object
2. Never read from the GET response in `loadSettings()`
3. Never appended to FormData in `saveSettings()`
4. Never accepted as Form params in `post_settings`
5. Never persisted to settings.json or live-patched on config

The GET endpoint already returned them correctly. Only POST and the Alpine wiring needed fixing.

**Fix (agent/main.py):** Added `anthropic_model: str = Form("")` and `openai_model: str = Form("")` params. Added persist with blank-preserves-existing fallback (same pattern as `ollama_model`). Added live-patch `config.anthropic_model = stored["anthropic_model"]` and `config.openai_model = stored["openai_model"]`.

**Fix (agent/templates/index.html):** Declared `anthropicModel: ''` and `openaiModel: ''` in the `agentUI()` return object. Added `this.anthropicModel = d.anthropic_model || ''` and `this.openaiModel = d.openai_model || ''` in `loadSettings()`. Added `fd.append('anthropic_model', ...)` and `fd.append('openai_model', ...)` in `saveSettings()`.

## Tests Added

| Test | Type | Covers |
|------|------|--------|
| test_settings_overlay_inside_agentui_scope | DOM position assertion | CR-01 |
| test_settings_overlay_not_in_outer_disclaimer_scope | DOM position assertion | CR-01 |
| test_post_settings_rejects_invalid_provider | HTTP 422 + no disk write | CR-02 |
| test_post_settings_accepts_each_valid_provider | HTTP 200 for all 3 providers | CR-02 |
| test_post_settings_persists_anthropic_model | disk + config round-trip | CR-03 |
| test_post_settings_persists_openai_model | disk + config round-trip | CR-03 |
| test_post_settings_blank_model_preserves_existing | blank-preserves fallback | CR-03 |

**Phase 11 test count: 32 (25 prior Plans 01-04 + 7 new Plan 05)**

## Commits

| # | Hash | Description |
|---|------|-------------|
| RED-1 | 1ba7731 | test(11-05): add RED regression tests for CR-01 overlay scope |
| GREEN-1 | 2d91173 | feat(11-05): Task 1 CR-01 — move settings overlay inside agentUI() Alpine scope |
| RED-2 | 07f078d | test(11-05): add RED tests for CR-02 provider enum gate + CR-03 model round-trip |
| GREEN-2 | ce392dd | feat(11-05): Task 2 CR-02+CR-03 — provider enum gate + anthropic/openai model round-trip |

## Deviations from Plan

None — plan executed exactly as written.

## Known Stubs

None — no placeholder values or hardcoded stubs introduced.

## Threat Flags

None — no new network endpoints, auth paths, or schema changes at trust boundaries. The provider gate (CR-02) reduces attack surface vs. the prior unconstrained form field.

## Self-Check: PASSED

- agent/templates/index.html exists and contains class="settings-overlay" exactly once
- agent/main.py exists and contains ALLOWED_PROVIDERS, anthropic_model Form param, provider gate, live-patch
- tests/unit/test_settings_phase11.py exists with 7 new tests
- Commits 1ba7731, 2d91173, 07f078d, ce392dd all present in git log
- 32 Phase 11 tests pass; 3 pre-existing Phase 8 failures unchanged

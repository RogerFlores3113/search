---
phase: 12
plan: "02"
subsystem: backend
tags: [tdd, green-phase, prompt-library, settings, runner, config]
dependency_graph:
  requires: [12-01]
  provides: [agent/settings.py::SEED_PROMPTS, agent/settings.py::seed_prompts_if_absent, agent/config.py::Settings.active_prompt_id, agent/config.py::Settings.prompts, agent/runner.py::_build_extend_system_message, agent/main.py::/api/settings-prompts-extension]
  affects: [12-03, 12-04]
tech_stack:
  added: []
  patterns: [pydantic-settings list[dict] field, first-init seeding pattern, Form-field-as-JSON-string pattern, GUARDRAIL_PROMPT suffix enforcement]
key_files:
  created: []
  modified:
    - agent/settings.py
    - agent/config.py
    - agent/runner.py
    - agent/main.py
decisions:
  - "GET /api/settings reads prompts from settings.json (stored dict) rather than config singleton to ensure fresh-install seeding is reflected immediately without lifespan dependency"
  - "seed_prompts_if_absent() does NOT live-patch config directly; lifespan() handles that after calling it"
  - "GUARDRAIL_PROMPT string never appears anywhere in main.py — comment referencing it was replaced with neutral wording"
metrics:
  duration: "4 minutes"
  completed: "2026-05-19T06:28:00Z"
  tasks_completed: 3
  tasks_total: 3
  files_changed: 4
---

# Phase 12 Plan 02: Prompt Library Backend Implementation Summary

**One-liner:** Backend slice — SEED_PROMPTS constant + seed_prompts_if_absent() + Settings fields + _build_extend_system_message() + /api/settings prompt round-trip, turning 9 of 12 RED tests GREEN.

## What Was Built

Pure backend implementation of the prompt library. No template or CSS changes. Defines the contract that Plan 03 (UI) consumes.

Four files modified:

1. **agent/settings.py** — `SEED_PROMPTS` constant (4 seed dicts) and `seed_prompts_if_absent()` function that writes seeds to settings.json on fresh install (one-shot, no-op if "prompts" key exists).

2. **agent/config.py** — Two new fields on `Settings(BaseSettings)`: `active_prompt_id: str = "generic"` and `prompts: list[dict] = []`. Loaded automatically by `JsonConfigSettingsSource` from settings.json.

3. **agent/runner.py** — `_build_extend_system_message(active_prompt_id, prompts) -> str` function placed after `GUARDRAIL_PROMPT` constant. GUARDRAIL_PROMPT is always the suffix — cannot be removed by user-supplied content. `extend_system_message=` in Agent() constructor now uses this builder.

4. **agent/main.py** — `lifespan()` calls `seed_prompts_if_absent()` before yield and live-patches `config.prompts` + `config.active_prompt_id`. GET `/api/settings` returns `prompts` and `active_prompt_id` (read from settings.json to handle fresh-install). POST `/api/settings` accepts `prompts_json` (JSON string) and `active_prompt_id` Form fields, validates entries, persists, and live-patches config.

## Task Results

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | SEED_PROMPTS + seed_prompts_if_absent; Settings config fields | daa4a03 | agent/settings.py, agent/config.py |
| 2 | _build_extend_system_message and Agent() rewire | e0b100e | agent/runner.py |
| 3 | /api/settings GET+POST + lifespan seed call | 9c79836 | agent/main.py |

## Verification

```
uv run pytest tests/unit/test_prompts_phase12.py -q
# → 9 passed, 3 failed (HTML inspection tests — expected RED for Plan 03)

uv run pytest tests/unit/ -q --ignore=tests/unit/test_prompts_phase12.py
# → 259 passed, 15 failed (same 15 pre-existing failures, no regression)

grep -c "GUARDRAIL_PROMPT" agent/main.py
# → 0 (safety guardrail constant not exposed via API surface)
```

## Test Mapping

| Test | Status | Notes |
|------|--------|-------|
| test_seed_prompts_written_when_absent | GREEN | Task 1 |
| test_seed_prompts_not_overwritten_if_present | GREEN | Task 1 |
| test_get_settings_returns_prompts | GREEN | Task 3 |
| test_save_prompts_persists_edit | GREEN | Task 3 |
| test_seed_prompts_not_deleted_via_api | GREEN | Task 3 |
| test_active_prompt_id_saved_and_live_patched | GREEN | Task 3 |
| test_guardrail_always_appended | GREEN | Task 2 |
| test_guardrail_fallback_when_no_active_prompt | GREEN | Task 2 |
| test_guardrail_not_in_api_response | GREEN | Task 3 |
| test_add_prompt_creates_entry | RED | Plan 03 (HTML) |
| test_active_prompt_label_in_html | RED | Plan 03 (HTML) |
| test_prompt_section_in_settings_overlay | RED | Plan 03 (HTML) |

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] GET /api/settings reads from stored dict, not config singleton**

- **Found during:** Task 3 first test run
- **Issue:** Tests monkeypatch `agent.settings.get_settings_path` but cannot easily patch the already-initialized `config` singleton. GET handler reading `config.prompts` returned `[]` instead of the test's seeded values.
- **Fix:** GET handler reads `prompts` and `active_prompt_id` from `stored = load_settings_json()` with fallback to `config.prompts`/`config.active_prompt_id`. This correctly reflects seeded data regardless of singleton state.
- **Files modified:** agent/main.py
- **Commit:** 9c79836

**2. [Rule 2 - Auto-fix] Removed GUARDRAIL_PROMPT literal from main.py comment**

- **Found during:** Task 3 acceptance criteria check
- **Issue:** A comment `# GUARDRAIL_PROMPT is NOT included here (T-12-01 mitigation)` was added, causing `grep -c "GUARDRAIL_PROMPT" agent/main.py` to return 1 instead of 0.
- **Fix:** Rewrote comment to not reference the constant by name.
- **Files modified:** agent/main.py
- **Commit:** 9c79836

## Threat Flags

None — no new network endpoints or auth paths introduced beyond what the plan defined.

## Known Stubs

None — all backend fields are fully wired. GET /api/settings returns real prompts from settings.json. POST persists and live-patches. GUARDRAIL_PROMPT suffix is enforced at the Python layer.

## Self-Check: PASSED

- [x] agent/settings.py modified (SEED_PROMPTS + seed_prompts_if_absent)
- [x] agent/config.py modified (active_prompt_id + prompts fields)
- [x] agent/runner.py modified (_build_extend_system_message + Agent() rewire)
- [x] agent/main.py modified (lifespan + GET + POST)
- [x] Commit daa4a03 exists
- [x] Commit e0b100e exists
- [x] Commit 9c79836 exists
- [x] 9 of 12 Phase 12 tests GREEN
- [x] 3 HTML tests remain RED (expected — Plan 03)
- [x] Phase 11 settings tests: 32 passed (no regression)
- [x] GUARDRAIL_PROMPT not in main.py (grep count = 0)

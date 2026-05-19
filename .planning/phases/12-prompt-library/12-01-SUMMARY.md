---
phase: 12
plan: "01"
subsystem: testing
tags: [tdd, red-phase, prompt-library, test-scaffolding]
dependency_graph:
  requires: []
  provides: [tests/unit/test_prompts_phase12.py]
  affects: [phase-12-wave-1, phase-12-wave-2]
tech_stack:
  added: []
  patterns: [pytest-asyncio auto mode, AsyncClient+ASGITransport, tmp_path+monkeypatch isolation, in-body imports for non-existent symbols]
key_files:
  created:
    - tests/unit/test_prompts_phase12.py
  modified: []
decisions:
  - "In-body imports for seed_prompts_if_absent and _build_extend_system_message ensure collection succeeds while producing ImportError as the RED failure condition"
  - "HTML inspection tests use Path('agent/templates/index.html').read_text() consistent with Phase 11 pattern"
  - "test_seed_prompts_not_deleted_via_api documents the locked decision that server accepts payload as sent (no server-side seed re-addition)"
metrics:
  duration: "4 minutes"
  completed: "2026-05-19T06:23:00Z"
  tasks_completed: 1
  tasks_total: 1
  files_changed: 1
---

# Phase 12 Plan 01: Prompt Library RED Test Scaffold Summary

**One-liner:** 12 RED test stubs pinning PROMPT-01 through PROMPT-07 acceptance contract before any source changes.

## What Was Built

A single test module `tests/unit/test_prompts_phase12.py` containing 12 failing test functions that lock every behavioral requirement for Phase 12 as executable assertions. Tests fail for the correct reason: missing symbols (`seed_prompts_if_absent`, `_build_extend_system_message`) produce `ImportError` inside the test body; HTML inspection tests fail because the required HTML elements don't exist yet.

## Task Results

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Create test_prompts_phase12.py with 12 RED stubs | b24278b | tests/unit/test_prompts_phase12.py |

## Verification

```
uv run pytest tests/unit/test_prompts_phase12.py --collect-only -q
# → 12 tests collected

uv run pytest tests/unit/test_prompts_phase12.py -x -q
# → 1 failed (ImportError on seed_prompts_if_absent — correct RED condition)

uv run pytest tests/unit/ -q --ignore=tests/unit/test_prompts_phase12.py
# → 259 passed (pre-existing failures unchanged: 15 known pre-existing failures)
```

## Test Inventory

| # | Test Name | Requirement | RED Reason |
|---|-----------|-------------|------------|
| 1 | test_seed_prompts_written_when_absent | PROMPT-06 | ImportError: seed_prompts_if_absent missing |
| 2 | test_seed_prompts_not_overwritten_if_present | PROMPT-06 | ImportError: seed_prompts_if_absent missing |
| 3 | test_get_settings_returns_prompts | PROMPT-01 | GET response lacks prompts key |
| 4 | test_add_prompt_creates_entry | PROMPT-02 | HTML missing addPrompt()/randomUUID()/is_seed |
| 5 | test_save_prompts_persists_edit | PROMPT-03 | POST handler lacks prompts_json field |
| 6 | test_seed_prompts_not_deleted_via_api | PROMPT-04 | POST handler lacks prompts_json field |
| 7 | test_active_prompt_id_saved_and_live_patched | PROMPT-05 | config lacks active_prompt_id field |
| 8 | test_guardrail_always_appended | PROMPT-07 | ImportError: _build_extend_system_message missing |
| 9 | test_guardrail_fallback_when_no_active_prompt | PROMPT-07 | ImportError: _build_extend_system_message missing |
| 10 | test_guardrail_not_in_api_response | PROMPT-07/T-12-01 | ImportError: _build_extend_system_message missing |
| 11 | test_active_prompt_label_in_html | PROMPT-01/05 | HTML missing active-prompt-label |
| 12 | test_prompt_section_in_settings_overlay | PROMPT-01/06 | HTML missing prompt-list/prompt-editor |

## Deviations from Plan

None — plan executed exactly as written.

## Threat Flags

None — this plan adds no production code or HTTP surface.

## Known Stubs

None — this is a test-only plan; no production stubs introduced.

## Self-Check: PASSED

- [x] tests/unit/test_prompts_phase12.py exists
- [x] Commit b24278b exists in git log
- [x] 12 tests collected by pytest
- [x] Tests produce RED (failed/error) on first run
- [x] No production files under agent/ modified

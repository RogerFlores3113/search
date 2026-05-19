---
phase: 13-task-presets-prompt-engineering-runner-wiring
plan: "01"
subsystem: tests
tags:
  - tdd
  - red-scaffold
  - phase-13
  - presets
  - prompt-engineering
dependency_graph:
  requires: []
  provides:
    - tests/unit/test_presets_phase13.py (Phase 13 acceptance contract — 12 RED tests)
  affects:
    - agent/templates/index.html (tested but not yet modified)
    - agent/settings.py (SEED_PROMPTS tested but not yet updated)
    - agent/runner.py (snapshot pattern tested but not yet implemented)
    - agent/db.py (prompt_id migration tested but not yet applied)
    - agent/main.py (/run endpoint tested but not yet extended)
    - agent/templates/runs_fragment.html (prompt_id rendering tested but not yet added)
tech_stack:
  added: []
  patterns:
    - deferred-import-inside-test-body (all agent.* imports inside test functions with # noqa: PLC0415)
    - db_dir fixture (tmp_path + monkeypatch.chdir for isolated DB writes)
    - Path.read_text HTML inspection (no import needed for template tests)
    - ASGITransport + AsyncClient (ASGI integration test for /run endpoint)
key_files:
  created:
    - tests/unit/test_presets_phase13.py
  modified: []
decisions:
  - "RED scaffold asserts symbols/HTML that do not exist — all 12 tests must fail on plan-01"
  - "deferred import pattern (inside test body) ensures pytest collection succeeds even when agent.* symbols are absent"
  - "db_dir fixture reuses pattern from test_db.py: tmp_path + monkeypatch.chdir for isolation"
  - "job prompt test explicitly asserts unauthenticated-only constraint per STATE.md blocker"
  - "test_runner_snapshot_prompt_id uses Path source inspection rather than runtime import to avoid import errors before implementation"
metrics:
  duration: ~5 minutes
  completed: "2026-05-19"
  tasks_completed: 2
  tasks_total: 2
  files_created: 1
  files_modified: 0
---

# Phase 13 Plan 01: RED Scaffold — Task Presets + Prompt Engineering + Runner Wiring Summary

**One-liner:** 12 RED pytest tests lock the Phase 13 acceptance contract covering preset UI buttons, applyPreset() Alpine method, engineered prompt content (ENG-01..04), runner snapshot wiring, DB migration, /run endpoint extension, and runs_fragment prompt display.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Create RED scaffold with 12 failing tests | baea20e | tests/unit/test_presets_phase13.py |
| 2 | Confirm full suite still green except Phase 13 RED tests | (no commit) | — |

## Test Functions Created

| Test | Requirement | What It Asserts |
|------|-------------|-----------------|
| test_preset_buttons_in_html | PRESET-01 | preset-row, btn-preset, 3 applyPreset() click handlers, 3 labels |
| test_apply_preset_method_in_html | PRESET-02 | applyPreset(presetSlug), PRESET_TEMPLATES, slugToPromptId, textarea querySelector, focus() |
| test_apply_preset_sets_active_prompt_id | PRESET-03 (frontend) | this.activePromptId = slugToPromptId[presetSlug], all 3 slug→id mappings |
| test_generic_prompt_eng01 | ENG-01 | 6 section headers (ENVIRONMENT, NUMBERED STEPS, etc.), ≥20 lines |
| test_apartment_prompt_eng02 | ENG-02 | 3 target sites, STOP CONDITIONS, JSON, address/price/bedrooms, pagination |
| test_job_prompt_eng03 | ENG-03 | LinkedIn/Indeed, STOP CONDITIONS, filter, unauthenticated constraint |
| test_candidate_prompt_eng04 | ENG-04 | STOP CONDITIONS, credibility signal, profile, source, JSON |
| test_prompt_id_column_migrated | DB migration | init_db() must add prompt_id column to runs table |
| test_insert_run_accepts_prompt_id | DB migration | insert_run() accepts prompt_id kwarg; round-trips via SELECT |
| test_runner_snapshot_prompt_id | PRESET-03 (backend) | snapshot_prompt_id var, active_prompt_id param, no config.active_prompt_id direct use |
| test_run_endpoint_accepts_active_prompt_id | PRESET-03 | active_prompt_id: str = Form( in main.py, passed to run_agent; ASGI POST returns 200/303/409 |
| test_runs_fragment_renders_prompt_id | UI | {% set _prompt_id %}, {% if _prompt_id %}, "System prompt:" in runs_fragment.html |

## Verification Results

- `uv run pytest tests/unit/test_presets_phase13.py --collect-only -q`: **12 tests collected, 0 errors**
- `uv run pytest tests/unit/test_presets_phase13.py -q`: **12 FAILED, 0 errors, 0 passed** (correct RED state)
- `uv run pytest tests/unit/ -q --ignore=tests/unit/test_presets_phase13.py`: **272 passed, 14 pre-existing failures** (same count as without scaffold file — scaffold introduced 0 new failures)
- No top-level `from agent` or `import agent` lines in test file (all deferred inside test bodies)

## Deviations from Plan

None — plan executed exactly as written.

## Known Stubs

None — this is a test-only plan; no source stubs created.

## Threat Flags

None — test file is dev-only, never shipped. No new network endpoints or trust boundaries introduced.

## Self-Check: PASSED

- [x] tests/unit/test_presets_phase13.py exists
- [x] Commit baea20e exists in git log
- [x] 12 tests collected, 12 RED failures, 0 errors

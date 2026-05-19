---
phase: 13-task-presets-prompt-engineering-runner-wiring
plan: "03"
subsystem: backend
tags: [backend, phase-13, db-migration, runner, snapshot]
dependency_graph:
  requires: [13-01]
  provides: [prompt_id column in runs table, runner config snapshot, active_prompt_id form field]
  affects: [agent/db.py, agent/runner.py, agent/main.py]
tech_stack:
  added: []
  patterns: [config snapshot before await, idempotent ALTER TABLE migration]
key_files:
  created: []
  modified:
    - agent/db.py
    - agent/runner.py
    - agent/main.py
    - tests/unit/test_presets_phase13.py
    - tests/unit/test_ui.py
decisions:
  - "snapshot_provider/model/prompt_id captured synchronously before any await in run_agent() to prevent mid-run config mutation affecting in-flight run"
  - "CR-01 fixed: step_start = time.monotonic() moved to after pre_flight_check succeeds in else branch"
  - "Test scaffold bug fixed: ASGI /run test needed disclaimer cookie (same pattern as test_ui.py _disclaimer_cookies)"
  - "test_ui.py stubs updated with **kwargs to accept new active_prompt_id keyword without TypeError"
metrics:
  duration: "~15 minutes"
  completed: "2026-05-19T08:17:08Z"
  tasks_completed: 3
  files_modified: 5
---

# Phase 13 Plan 03: Runner Config Snapshot + prompt_id Column Summary

Runner config snapshot wired end-to-end: prompt_id TEXT column added to runs table via idempotent migration, run_agent() snapshots provider/model/active_prompt_id before any await, /run endpoint accepts active_prompt_id as Form field, and the snapshot persists on the run history row. CR-01 (step_start timer before pre_flight_check) fixed.

## Tasks Completed

| Task | Name | Commit | Key Files |
|------|------|--------|-----------|
| 1 | Add prompt_id column + extend insert_run/list_runs | 6c4978f | agent/db.py |
| 2 | Runner snapshot + CR-01 fix + active_prompt_id parameter | 810df4e | agent/runner.py |
| 3 | /run endpoint accepts active_prompt_id Form field | c685d9a | agent/main.py, tests/unit/test_presets_phase13.py, tests/unit/test_ui.py |

## Verification

All 4 backend-owned Phase 13 RED tests now GREEN:
- test_prompt_id_column_migrated PASSED
- test_insert_run_accepts_prompt_id PASSED
- test_runner_snapshot_prompt_id PASSED
- test_run_endpoint_accepts_active_prompt_id PASSED

Pre-existing test suite unaffected (14 failures baseline, same 14 after changes — 6 in test_runner.py related to environment/monkeypatching, 7 pre-phase-13 RED tests, 1 header-ticker in test_events_phase9.py).

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed missing disclaimer cookie in test scaffold**
- **Found during:** Task 3
- **Issue:** test_presets_phase13.py ASGI /run call returned 403 because it lacked the signed disclaimer cookie required by the disclaimer gate (added Phase 11)
- **Fix:** Added `DISCLAIMER_COOKIE_NAME`/`_disclaimer_serializer` import and passed disclaimer cookie to ASGI client, matching the pattern in test_ui.py `_disclaimer_cookies()`
- **Files modified:** tests/unit/test_presets_phase13.py
- **Commit:** c685d9a

**2. [Rule 1 - Bug] Fixed test_ui.py stubs broken by new keyword argument**
- **Found during:** Task 3
- **Issue:** `stub_run_agent` and `quick_run_agent` in test_ui.py used fixed signature `(task, *, queue=None, control_queue=None)` — adding `active_prompt_id` to run_agent() caused TypeError when /run passed it
- **Fix:** Added `**kwargs` to both stub signatures
- **Files modified:** tests/unit/test_ui.py
- **Commit:** c685d9a

## Known Stubs

None — all data flows are fully wired. prompt_id is persisted from the Form field through the snapshot to the DB row.

## Threat Flags

No new threat surface beyond what the plan's threat model covers. T-13-03-01 (active_prompt_id as dict-lookup key with safe fallback) and T-13-03-02 (snapshot before await) are both mitigated as designed.

## Self-Check: PASSED

- agent/db.py modified: confirmed (prompt_id in _AGGREGATE_COLUMNS, insert_run, list_runs)
- agent/runner.py modified: confirmed (snapshot_provider, snapshot_model, snapshot_prompt_id, active_prompt_id param, CR-01 fix)
- agent/main.py modified: confirmed (active_prompt_id: str = Form("generic"), active_prompt_id=active_prompt_id in create_task)
- Commits 6c4978f, 810df4e, c685d9a: all present in git log

---
phase: 03-full-web-ui
plan: "01"
subsystem: web-ui
tags:
  - phase-03
  - sse
  - htmx
  - asyncio-queue
  - sqlite
  - vertical-slice

dependency_graph:
  requires:
    - 01-scaffold-core-loop-poc
    - 02-multi-provider-guardrails
  provides:
    - asyncio.Queue SSE bridge (D-11)
    - agent/events.py event dataclasses
    - agent/db.py aiosqlite helpers
    - GET / HTMX+Alpine index.html
    - POST /run SSE queue wiring
    - GET /stream EventSourceResponse
  affects:
    - agent/runner.py (queue param, NarrationEvent, DoneEvent guarantee)
    - agent/main.py (SSE endpoint, lifespan init_db, GET /)

tech_stack:
  added:
    - aiosqlite>=0.20 (SQLite async I/O)
    - fastapi.sse.EventSourceResponse
    - fastapi.templating.Jinja2Templates
    - fastapi.staticfiles.StaticFiles
    - HTMX 2.0.10 (CDN)
    - htmx-ext-sse 2.2.4 (CDN)
    - Alpine.js 3.15.12 (CDN)
  patterns:
    - asyncio.Queue bridge between run_agent and GET /stream (D-11 locked contract)
    - Jinja2 server-side templates (no build step)
    - SSE via EventSourceResponse + async generator
    - DoneEvent sentinel guarantees stream always terminates

key_files:
  created:
    - agent/events.py (7 dataclass event types with Literal discriminant)
    - agent/db.py (init_db, insert_run, list_runs with parameterized SQL)
    - agent/templates/index.html (HTMX+Alpine two-column UI skeleton)
    - tests/unit/test_db.py (4 passing DB tests incl. SQL injection test)
    - tests/unit/test_ui.py (14 tests: 9 passing, 5 skipped Plan 02/03)
  modified:
    - pyproject.toml (added aiosqlite>=0.20)
    - uv.lock (updated lockfile)
    - agent/runner.py (queue param, NarrationEvent, DoneEvent always emitted)
    - agent/main.py (SSE endpoint, lifespan init_db, GET /, POST /run queue wiring)
    - .gitignore (added data/ for runtime SQLite DB)

decisions:
  - "Used stdlib dataclasses (not pydantic) for events.py per D-11 interface — dataclasses.asdict() is used in the SSE endpoint for JSON serialization"
  - "NarrationEvent-only emission in Plan 01 _log_step; ScreenshotEvent and ProgressEvent deferred to Plan 02 per task spec"
  - "history_db.insert_run deferred from runner.finally to Plan 03 per task spec — db.py helpers are functional now for test roundtrips"
  - "Alpine handleNarration uses textContent (not innerHTML) to mitigate XSS (T-03-02)"
  - "StaticFiles mounted with check_dir=False so startup does not crash before agent/static is populated"
  - "data/ added to .gitignore — runtime SQLite directory should not be committed"

metrics:
  duration_minutes: 6
  tasks_completed: 2
  files_created: 5
  files_modified: 5
  completed_date: "2026-05-16"
---

# Phase 03 Plan 01: SSE Skeleton + asyncio.Queue Bridge Summary

**One-liner:** Delivered end-to-end vertical slice — asyncio.Queue bridges run_agent to GET /stream SSE, DoneEvent guarantees stream always closes, HTMX+Alpine index.html renders live narration feed with XSS-safe textContent, aiosqlite DB helpers functional with parameterized SQL injection mitigation.

## What Shipped

### Task 1: Wave 0 contracts
- `aiosqlite>=0.20` added to `pyproject.toml`; lockfile updated to aiosqlite 0.22.1
- `agent/events.py` — 7 dataclass event types (ScreenshotEvent, NarrationEvent, StateEvent, ProgressEvent, SummaryEvent, ErrorEvent, DoneEvent) each with a `Literal` type discriminant for SSE event routing
- `agent/db.py` — init_db (CREATE TABLE IF NOT EXISTS), insert_run, list_runs; all SQL uses `?` placeholder parameters (T-03-01 SQL injection mitigation); DB_PATH = `Path("data/history.db")`
- `tests/unit/test_db.py` — 4 passing tests covering roundtrip, DESC ordering, limit=10, and SQL injection guard
- `tests/unit/test_ui.py` — Wave 0 scaffold with 14 test function stubs (all 13 VALIDATION.md names + `test_event_dataclasses_have_type_discriminant`)

### Task 2: Queue bridge + SSE endpoint + index.html
- `agent/runner.py` — `run_agent(task, queue=None)` signature; `browser=None` guard before try (PreFlightError path safety); `StateEvent("running")` emitted at start; `NarrationEvent` emitted in `_log_step` after existing JSONL write (RUN-03 preserved); outer `finally` always emits `DoneEvent()` regardless of exit path (D-11)
- `agent/main.py` — `_active_queue` and `_active_agent` module-level refs; `lifespan` calls `await history_db.init_db()`; `GET /` returns Jinja2 `index.html`; `POST /run` creates `asyncio.Queue`, sets `_active_queue`, passes `queue=queue` to `run_agent`, returns `HX-Trigger: streamStarted`; `GET /stream` async generator drains queue until `DoneEvent`
- `agent/templates/index.html` — Two-column layout: left screenshot viewport, right control panel with state badge, task form, narration feed, Pause/Stop placeholders (disabled, Plan 03)

## Test Results

```
uv run pytest tests/unit/ -q --tb=short
54 passed, 7 skipped in 1.10s
```

- 9 test_ui.py tests passing (dataclass discriminant + 8 Task 2 behaviors)
- 5 test_ui.py tests skipped (Plan 02/03 deferrals: pause, stop, screenshot, summary, GET /runs)
- 4 test_db.py tests passing
- 20 test_runner.py tests passing (no regressions)

## Deviations from Plan

### Auto-fixed Issues

None — plan executed exactly as designed.

### Minor implementation decisions

**1. [Rule 2 - Missing feature] Added test_post_run_busy**
- The plan's behavior list for Task 2 included `test_post_run_busy` (second POST /run returns 409) but the VALIDATION.md stub list did not include it as a named stub. Added the test alongside `test_post_run_returns_started` as it is required for the 409 behavior contract.

**2. [Rule 2 - Missing feature] Added `test_get_index_returns_html`**
- Task 2 behavior list specified this test but VALIDATION.md did not include it in the 13 required names. Added as an additional test since GET / is implemented in Task 2.

**3. data/ directory gitignore**
- Running the aiosqlite tests during development created `data/history.db` in the worktree working directory. Added `data/` to `.gitignore` (separate chore commit) to prevent accidental commit of the runtime DB.

## Security Scan

All threat mitigations from the plan's STRIDE threat register were implemented:

| Threat ID | Mitigation | Verified |
|-----------|------------|---------|
| T-03-01 | agent/db.py uses `?` placeholders; `test_insert_run_uses_parameterized_query` passes | `grep -E "%s\|format\|f\"" agent/db.py` returns 0 SQL lines |
| T-03-02 | index.html uses `x-text` (Alpine) and DOM `textContent` in handleNarration; no `innerHTML` or `\| safe` | acceptance grep confirms 0 matches |
| T-03-03 | ErrorEvent.message = `str(e)` only; no `traceback.format_exc()` in runner | code review |
| T-03-06 | GET /stream captures local `queue = _active_queue` at connection time | code review |

No new threat surface introduced beyond what is documented in the plan's threat model.

## Open Items Handed to Plan 02

- ScreenshotEvent emission in `_log_step` (Plan 02 wires `b64` capture)
- ProgressEvent emission in `_log_step` (Plan 02)
- Inline screenshot `<img>` src update in the UI (Plan 02)
- Progress counter display (Plan 02)
- SummaryEvent inline display wiring (Plan 02)
- ErrorEvent inline display wiring (Plan 02)

## Open Items Handed to Plan 03

- `history_db.insert_run` call from `runner.finally` (Plan 03)
- GET /runs endpoint (Plan 03)
- POST /pause and POST /stop endpoints (Plan 03)
- `_active_agent` wired from runner via callback (Plan 03)
- Full run history display in UI (Plan 03)

## Self-Check

Files created and verified:
- agent/events.py — FOUND
- agent/db.py — FOUND
- agent/main.py — MODIFIED, verified GET / returns 200 with SSE attributes
- agent/runner.py — MODIFIED, verified queue bridge and DoneEvent guarantee
- agent/templates/index.html — FOUND
- tests/unit/test_db.py — FOUND
- tests/unit/test_ui.py — FOUND

Commits:
- 8a0d4fe — Task 1 (events.py, db.py, Wave 0 scaffold)
- 2029e39 — Task 2 (runner queue bridge, main.py SSE, index.html)
- da85c63 — chore (.gitignore data/)

## Self-Check: PASSED

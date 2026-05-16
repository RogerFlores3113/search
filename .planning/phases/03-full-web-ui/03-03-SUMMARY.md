---
phase: 03-full-web-ui
plan: "03"
subsystem: web-ui
tags:
  - phase-03
  - controls
  - history
  - pause-stop
  - vertical-slice

dependency_graph:
  requires:
    - 03-01 (asyncio.Queue SSE bridge, events.py, db.py, index.html skeleton)
    - 03-02 (style.css, screenshot + progress UI, result-area)
  provides:
    - POST /pause endpoint (pause/resume toggle with StateEvent emission)
    - POST /stop endpoint (sync agent.stop())
    - GET /runs endpoint (last 10 runs as HTML fragment)
    - runner.finally inserts run record to history DB (status=error/stopped/complete)
    - runner sets/clears _active_agent module-level ref for /pause and /stop
    - runs_fragment.html Jinja2 partial with Jinja2 auto-escape (T-03-02)
    - index.html Pause/Stop buttons wired to endpoints
    - index.html run history panel with hx-get=/runs on load + SSE close
  affects:
    - agent/runner.py (deferred import, insert_run in finally, _active_agent set/clear)
    - agent/main.py (3 new endpoints, StateEvent import)
    - agent/templates/index.html (buttons and run history section)
    - agent/templates/runs_fragment.html (new file)
    - tests/unit/test_ui.py (17 new tests, zero remaining skips)

tech_stack:
  added: []
  patterns:
    - Deferred `from agent import main as _main_module` inside run_agent (circular import safe)
    - Sync pause/resume/stop calls — browser_use Agent.pause/resume/stop are synchronous (RESEARCH Pattern 5)
    - try/except around insert_run in finally — DB failure never blocks browser.kill()
    - Jinja2 auto-escape on all run fields in runs_fragment.html (no | safe filter anywhere)
    - hx-trigger="load, htmx:sseClose from:#sse-container" for post-run history refresh
    - monkeypatch.setattr DB_PATH instead of chdir for test isolation (template path safe)

key_files:
  created:
    - agent/templates/runs_fragment.html (Jinja2 partial — run list with auto-escape, empty state)
  modified:
    - agent/main.py (POST /pause, POST /stop, GET /runs endpoints + StateEvent import)
    - agent/runner.py (deferred _active_agent set, insert_run in finally, clear refs in finally)
    - agent/templates/index.html (Pause/Stop buttons wired, run history section added)
    - tests/unit/test_ui.py (17 new tests — all passing, zero skips remaining)

decisions:
  - "Deferred import `from agent import main as _main_module` inside run_agent body to avoid circular import — agent/main.py imports from agent/runner.py at module level, so a top-level import would create a circular dependency"
  - "insert_run wrapped in try/except in the outer finally block — DB failure (disk full, corruption) must never prevent browser.kill() from running or mask the original exception"
  - "Clearing _main_module._active_queue = None in runner finally follows D-11 locked contract — stale SSE consumers detect run ended when queue is None"
  - "Used monkeypatch.setattr(agent.db.DB_PATH, ...) instead of monkeypatch.chdir() for DB isolation in tests — chdir would break Jinja2 relative template path lookup"
  - "hx-trigger uses htmx:sseClose (HTMX documented event name) not sseClose — HTMX fires htmx:sseClose on the SSE container element when SSE connection closes"
  - "test_runs_fragment_escapes_task asserts &lt;script&gt; appears in output (Jinja2 auto-escape) — no | safe filter anywhere in runs_fragment.html (T-03-02 mitigation)"

metrics:
  duration_minutes: 25
  tasks_completed: 2
  files_created: 2
  files_modified: 3
  completed_date: "2026-05-16"
---

# Phase 03 Plan 03: Pause/Stop Controls + Run History Summary

**One-liner:** Wired pause/stop/runs endpoints to active browser-use Agent with sync toggle API, persisted run history via runner.finally insert_run, and rendered run history panel in index.html with Jinja2 auto-escaped fragment and hx-trigger SSE close refresh.

## What Shipped

### Task 1: Wire pause/stop endpoints + active_agent threading + history insert

**agent/main.py** — 3 new endpoints:
- `POST /pause` — toggles `_active_agent.pause()` / `_active_agent.resume()` (sync, no await per RESEARCH Pattern 5). Emits `StateEvent(state="paused")` or `StateEvent(state="running")` to `_active_queue`. Returns 400 + `{"status": "no_active_run"}` when no agent is active.
- `POST /stop` — calls `_active_agent.stop()` (sync). Returns 400 when no agent active.
- `GET /runs` — calls `history_db.list_runs(limit=10)`, renders `runs_fragment.html`.

**agent/runner.py** — 3 changes in `run_agent`:
1. After `Agent(...)` construction, sets `_main_module._active_agent = agent` (deferred import to avoid circular import).
2. In outer finally, calls `await history_db.insert_run(...)` with `run_id`, `task`, `status` (error/stopped/complete), `summary`, `started_at`, `completed_at`. Wrapped in `try/except` so DB failure never blocks `browser.kill()`.
3. At end of finally, clears `_main_module._active_agent = None` and `_main_module._active_queue = None`.

**agent/templates/runs_fragment.html** — new Jinja2 partial:
- If `runs` is empty: shows `<p class="empty-state">No runs yet. Enter a task above to start.</p>`
- Else: `<ul class="runs-list">` with one `<li>` per run containing task (truncated at 60 chars), status badge, and timestamp.
- All variables use `{{ }}` auto-escape — no `| safe` filter anywhere (T-03-02 mitigation).

### Task 2: Render run history panel + enable Pause/Stop buttons

**agent/templates/index.html** — 2 changes:
1. Replaced disabled Pause/Stop button placeholders with:
   - Pause: `hx-post="/pause"` `hx-swap="none"` `:disabled="state !== 'running' && state !== 'paused'"` `x-text="state === 'paused' ? 'Resume' : 'Pause'"`
   - Stop: `hx-post="/stop"` `hx-swap="none"` `:disabled="state !== 'running' && state !== 'paused'"`
2. Added `<section id="run-history">` inside `#sse-container` (before closing tag) with `hx-get="/runs"` `hx-trigger="load, htmx:sseClose from:#sse-container"` `hx-swap="innerHTML"`.

## Test Results

```
uv run pytest tests/unit/ -q --tb=short
81 passed in 1.46s
```

- 17 new tests across Task 1 and Task 2 (all passing)
- 0 skips remaining in tests/unit/test_ui.py (previously 5 skips)
- Full test suite: 81 tests, 0 failures

## Phase 3 Requirement Coverage

All 17 Phase 3 requirement IDs:

| Requirement | Coverage | Status |
|-------------|----------|--------|
| LOOP-01 | POST /run starts agent (Plan 01) | Automated |
| LOOP-07 | POST /pause toggles pause/resume | Automated (new) |
| LOOP-08 | POST /stop terminates agent | Automated (new) |
| LOOP-09 | NarrationEvent per step | Automated (Plan 01) |
| LOOP-10 | SummaryEvent on success | Automated (Plan 02) |
| UI-01 | Single-page HTMX layout | Automated (Plan 01) |
| UI-02 | ScreenshotEvent streamed to UI | Automated (Plan 02) |
| UI-03 | State badge updates (idle/running/paused/complete/error) | Automated (Plan 01) |
| UI-04 | StateEvent emission from runner | Automated (Plan 01) |
| UI-05 | Progress counter Step N of M | Automated (Plan 02) |
| UI-06 | Pause button wired to /pause | Automated (new) |
| UI-07 | Stop button wired to /stop | Automated (new) |
| UI-08 | ErrorEvent inline display | Automated (Plan 02) |
| UI-09 | SummaryEvent inline display | Automated (Plan 02) |
| RUN-01 | insert_run in runner.finally | Automated (new) |
| RUN-02 | GET /runs returns last 10 runs | Automated (new) |
| RUN-03 | JSONL per-step write to training/runs.jsonl | Automated (Plan 01) — confirmed preserved |

## RUN-03 Invariant Preserved

```
grep -n "TRAINING_FILE\|_write_jsonl\|to_thread" agent/runner.py
29:TRAINING_FILE = Path("training/runs.jsonl")
148:def _write_jsonl(path: Path, record: dict) -> None:
199:    await asyncio.to_thread(_write_jsonl, TRAINING_FILE, record)
```

The JSONL write path in `log_step` is unchanged. `insert_run` is an additive call in the outer finally — it does not touch the per-step JSONL write path.

## File Structure Created Across Phase 3

```
agent/
  events.py           — 7 dataclass event types (Plan 01)
  db.py               — init_db, insert_run, list_runs with parameterized SQL (Plan 01)
  main.py             — POST /run, POST /pause, POST /stop, GET /runs, GET /, GET /stream
  runner.py           — run_agent with queue bridge, NarrationEvent, insert_run, _active_agent threading
  static/
    style.css         — full dark-theme stylesheet, UI-SPEC tokens (Plan 02)
  templates/
    index.html        — HTMX+Alpine two-column UI with Pause/Stop and run history
    runs_fragment.html — Jinja2 partial for recent runs list
tests/unit/
  test_db.py          — 4 DB tests (Plan 01)
  test_ui.py          — 36 tests, 0 skips
```

## Manual Smoke Checklist (before /gsd-verify-work)

1. `uv run uvicorn agent.main:app --host 127.0.0.1 --port 8080 --reload`
2. Submit "go to wikipedia.org and find the Eiffel Tower" — observe screenshots stream, narration appends, badge=running
3. Click Pause mid-run — verify Chrome stops issuing actions, badge=paused
4. Click Resume — verify agent continues, badge=running
5. Click Stop on a new run — verify Chrome closes, no orphan processes (`pgrep chrome`), badge=complete or error, history row appears with status=stopped
6. Reload page — verify Recent Runs list shows the last 10 entries
7. Trigger error path: stop Ollama → Run → verify error_box shows friendly message, no traceback in DOM

## Open Items Deferred to v2

- Preset selector (structured task templates)
- Screenshot replay / timeline viewer
- CSV/Excel export of run history
- Multi-user / authentication (out of v1 scope)
- Auto-advance max_steps configuration in UI

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Missing feature] Changed db_dir fixture from chdir to setattr(DB_PATH)**
- **Found during:** Task 1 test_get_runs_returns_history — Jinja2 TemplateNotFound when monkeypatch.chdir(tmp_path) changed CWD so `agent/templates` was no longer resolvable
- **Issue:** The plan's `<action>` suggested using a `db_dir` fixture (or `chdir tmp_path`) — chdir broke Jinja2's relative template path `agent/templates`
- **Fix:** Changed fixture to use `monkeypatch.setattr(agent.db, "DB_PATH", tmp_path / "data" / "history.db")` so CWD stays at project root
- **Files modified:** tests/unit/test_ui.py
- **Commit:** cff5f40

No other deviations — plan executed as written.

## Security Scan

All threat mitigations from the plan's STRIDE threat register confirmed:

| Threat ID | Mitigation | Verified |
|-----------|------------|---------|
| T-03-01 | insert_run uses ? parameterized SQL (inherited from Plan 01) | grep confirms no f-string SQL |
| T-03-02 | runs_fragment.html uses {{ }} auto-escape; no \| safe filter | test_runs_fragment_escapes_task passes |
| T-03-09 | /pause and /stop return 400 idempotently when no run active | test_post_pause_no_active_run, test_post_stop_no_active_run pass |
| T-03-10 | pause/resume/stop are sync (GIL-safe); no true concurrency risk | RESEARCH Open Question Q3 accepted |

No new threat surface introduced beyond what is documented in the plan's threat model.

## Known Stubs

None. All plan goals are fully implemented:
- pause/stop are wired end-to-end
- run history is persisted and rendered
- All 36 tests pass with zero skips

## Self-Check

Files created and verified:
- agent/templates/runs_fragment.html — FOUND
- agent/main.py — MODIFIED, verified POST /pause, /stop, GET /runs endpoints
- agent/runner.py — MODIFIED, verified insert_run + _active_agent threading
- agent/templates/index.html — MODIFIED, verified Pause/Stop buttons + run history panel
- tests/unit/test_ui.py — MODIFIED, 36 tests 0 skips

Commits verified:
- 7196100 — test(03-03): RED tests for Task 1
- cff5f40 — feat(03-03): GREEN Task 1 implementation
- 5b2ada6 — test(03-03): RED tests for Task 2
- 2b57069 — feat(03-03): GREEN Task 2 implementation

## Self-Check: PASSED

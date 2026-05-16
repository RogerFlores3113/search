---
phase: 03-full-web-ui
plan: "02"
subsystem: web-ui
tags:
  - phase-03
  - sse
  - screenshots
  - alpine
  - vertical-slice

dependency_graph:
  requires:
    - 03-01 (asyncio.Queue SSE bridge, events.py dataclasses, index.html skeleton)
  provides:
    - ScreenshotEvent emission from _log_step (UI-02)
    - ProgressEvent emission from _log_step (UI-05)
    - SummaryEvent conditional emit on success (LOOP-10)
    - agent/static/style.css full UI-SPEC token implementation
    - Alpine handleProgress wired to ProgressEvent
    - #result-area with x-show summary + errorMsg (UI-08, UI-09)
    - Progress counter "Step N of M · Xs" with elapsed timer (UI-05)
  affects:
    - agent/runner.py (_log_step emits ScreenshotEvent + ProgressEvent)
    - agent/templates/index.html (CSS link, result-area, progress counter, handlers)
    - agent/static/style.css (new file — full dark-theme stylesheet)

tech_stack:
  added: []
  patterns:
    - ScreenshotEvent base64 string extracted null-safely from agent.history.screenshots()[-1]
    - ProgressEvent step counter from history.number_of_steps() - 1
    - Alpine setInterval elapsed timer started on StateEvent('running'), cleared on complete/error/idle
    - CSS custom properties at :root for full color and spacing token system
    - createElement+textContent DOM API for narration rows (XSS mitigation T-03-02)

key_files:
  created:
    - agent/static/style.css (387 lines — full UI-SPEC dark theme, responsive layout, component styles)
  modified:
    - agent/runner.py (_log_step emits ScreenshotEvent + ProgressEvent after NarrationEvent)
    - agent/templates/index.html (CSS link, progress counter, #result-area, filled handleProgress)
    - tests/unit/test_ui.py (5 new tests for Task 1, 5 new tests for Task 2; un-skipped Plan 02 stubs)

decisions:
  - "ScreenshotEvent emitted from _log_step closure after NarrationEvent; b64 extracted null-safely with `screenshots[-1] if (screenshots and screenshots[-1]) else ''; ScreenshotEvent always emitted even on empty screenshots so the SSE stream never breaks"
  - "ProgressEvent emitted from _log_step using step_idx+1 (from number_of_steps()-1) and config.max_steps"
  - "SummaryEvent already present in runner finally block from Plan 01; no changes needed; conditional on `if summary:` guard already present"
  - "handleError sets errorMsg only; ' — check your config and try again.' appended via x-text template binding per UI-SPEC Copywriting Contract"
  - "Removed inline <style> block from index.html; replaced with <link rel=stylesheet href=/static/style.css>"
  - "StaticFiles directory agent/static/ created so CSS is served; check_dir=False was already set in Plan 01"
  - "handleNarration creates DOM nodes via createElement+textContent in all three spans (step-num, narration-text, timestamp) — never innerHTML (T-03-02)"

metrics:
  duration_minutes: 4
  tasks_completed: 2
  files_created: 1
  files_modified: 3
  completed_date: "2026-05-16"
---

# Phase 03 Plan 02: Live Screenshot + Progress + Summary/Error UI Summary

**One-liner:** Wired ScreenshotEvent + ProgressEvent emission from _log_step closure, created full CSS dark-theme stylesheet with UI-SPEC tokens, and activated Alpine progress counter + inline result area so the UI renders live screenshots, step counter, summary, and errors end-to-end.

## What Shipped

### Task 1: Emit ScreenshotEvent + ProgressEvent + SummaryEvent from run_agent

- `agent/runner.py` — After the existing NarrationEvent put_nowait in `_log_step`, now also:
  1. Extracts `screenshots = agent_instance.history.screenshots()` with null-safe guard: `b64 = screenshots[-1] if (screenshots and screenshots[-1]) else ""`
  2. Emits `queue.put_nowait(ScreenshotEvent(b64=b64))` — always emitted even on empty screenshots (prevents SSE stream break)
  3. Emits `queue.put_nowait(ProgressEvent(step=step_idx+1, max_steps=config.max_steps))`
- `SummaryEvent` was already present in the outer `finally` block (Plan 01 implemented it), conditional on `if summary:` — no changes needed
- No changes to `agent/main.py` — the SSE endpoint already serializes all event types via `dataclasses.asdict()` + `event=event.type`

### Task 2: Wire Alpine handlers + full CSS

- `agent/static/style.css` — 387 lines implementing all UI-SPEC tokens:
  - `:root` custom properties: `--bg-dominant`, `--bg-panel`, `--accent`, `--destructive`, `--text-primary`, `--text-secondary`, `--text-placeholder`, `--border`, `--border-button`
  - Spacing tokens: `--sp-xs` through `--sp-xl`
  - `.badge-gray .badge-blue .badge-yellow .badge-green .badge-red` with exact UI-SPEC color pairs
  - `.narration-feed { max-height: 300px; overflow-y: auto; }` with `.narration-row`, `.step-num`, `.narration-text`, `.timestamp`
  - `.btn`, `.btn-primary`, `.btn-neutral`, `.btn-destructive` with 40px height, `:focus-visible` outline, `:disabled` opacity
  - `.result-area`, `.summary-box` (border-left #14532d), `.error-box` (border-left #ef4444)
  - `.progress-counter` label
  - `.run-history-*` classes for Plan 03
  - `@media (max-width: 767px)` responsive collapse (screenshot first, single column)

- `agent/templates/index.html` updates:
  - Removed inline `<style>` block; added `<link rel="stylesheet" href="/static/style.css">`
  - Progress counter span with Alpine x-show + template literal: `Step ${stepNum} of ${maxSteps} · ${elapsed}s`
  - `<div id="result-area">` with `.summary-box` (`x-show="summary"`, `role="status"`) and `.error-box` (`x-show="errorMsg"`, `role="alert"`)
  - `handleProgress($event)` — parses JSON, sets `this.stepNum = d.step; this.maxSteps = d.max_steps`
  - `handleState($event)` — starts `setInterval` elapsed timer on `running`, clears on `complete/error/idle`
  - `handleNarration($event)` — createElement + textContent for three child spans (XSS-safe, T-03-02)

## Test Results

```
uv run pytest tests/unit/ -q --tb=short
64 passed, 5 skipped in 1.07s
```

- Task 1 tests (5 new): test_log_step_emits_screenshot_event, test_log_step_emits_screenshot_event_empty_when_no_screenshots, test_log_step_emits_progress_event, test_run_agent_emits_summary_event, test_run_agent_omits_summary_when_no_final_result — all pass
- Task 2 tests (5 new): test_get_index_contains_alpine_handlers, test_get_index_has_result_area, test_get_index_links_stylesheet, test_static_css_served, test_index_no_unsafe_html — all pass
- All Plan 01 tests continue to pass (no regressions)
- 5 remaining skips: Plan 03 pause/stop/history tests

## Deviations from Plan

None — plan executed exactly as written.

The plan's must_haves artifact spec for `agent/main.py` states "Unchanged SSE endpoint already handles all event types via dataclasses.asdict — no endpoint changes needed". This was confirmed: no changes to main.py were required.

## Security Scan

All threat mitigations from the plan's STRIDE threat register confirmed:

| Threat ID | Mitigation | Verified |
|-----------|------------|---------|
| T-03-02 | handleNarration uses createElement+textContent (three spans); `grep -E "innerHTML\s*=" agent/templates/index.html` returns 0; `grep -E "\|\s*safe" agent/templates/index.html` returns 0 | PASS |
| T-03-03 | ErrorEvent.message set via `this.errorMsg = d.message`; displayed via x-text (not x-html) | PASS |
| T-03-07 | Screenshots streamed only to localhost consumer; not persisted to DB (history table excluded) | Accepted |
| T-03-08 | Screenshot b64 size capped by browser-use llm_screenshot_size (1024x640); event cadence ~1-2/sec | Accepted |

No new threat surface introduced.

## Open Items Handed to Plan 03

- `history_db.insert_run` call from `runner.finally` (record task, status, timestamps to SQLite)
- `GET /runs` endpoint returning last 10 run records as HTML fragment
- Run history rendering in `index.html` below the two-column layout
- POST `/pause` endpoint — call `_active_agent.pause()` / `_active_agent.resume()` toggle
- POST `/stop` endpoint — call `_active_agent.stop()`
- `_active_agent` module-level ref to be threaded from `run_agent` via callback or attribute set on task start
- Pause/Stop button `:disabled` binding changed from always-disabled to `state !== 'running' && state !== 'paused'` (already added in this plan as placeholders; endpoints not wired)

## Self-Check

Files verified:
- agent/static/style.css — FOUND (387 lines)
- agent/templates/index.html — MODIFIED
- agent/runner.py — MODIFIED
- tests/unit/test_ui.py — MODIFIED

Commits verified:
- c2f7dfe — test(03-02): RED tests for Task 1
- b523a24 — feat(03-02): GREEN implementation for Task 1
- b8b4a34 — test(03-02): RED tests for Task 2
- df74513 — feat(03-02): GREEN implementation for Task 2

## Self-Check: PASSED

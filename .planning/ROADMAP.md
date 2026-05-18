# Roadmap: local-browser-agent

## Milestones

- ✅ **v0.1.0 MVP** — Phases 1-4 (shipped 2026-05-16)
- 🚧 **v0.2.0 Foundations** — Phases 5-9 (in progress)

## Phases

<details>
<summary>✅ v0.1.0 MVP (Phases 1-4) — SHIPPED 2026-05-16</summary>

- [x] Phase 1: Scaffold + Core Loop PoC (3/3 plans) — completed 2026-05-13
- [x] Phase 2: Multi-Provider + Guardrails (2/2 plans) — completed 2026-05-15
- [x] Phase 3: Full Web UI (3/3 plans) — completed 2026-05-16
- [x] Phase 4: Distribution (2/2 plans) — completed 2026-05-16

See archive: `.planning/milestones/v0.1.0-ROADMAP.md`

</details>

### 🚧 v0.2.0 Foundations (In Progress)

**Milestone Goal:** Harden the core loop — instrument performance, surface model transparency, fix screenshot lag, and build the training data pipeline before expanding features.

- [x] **Phase 5: Token Counting + Timing** (2/2 plans) — completed 2026-05-17
- [x] **Phase 6: Model Transparency** (2/2 plans) — completed 2026-05-17
- [ ] **Phase 7: Screenshot Streaming** - Replace step-completion screenshots with a background 500ms capture loop; eliminate delivery lag with bounded queue and graceful teardown
- [x] **Phase 8: Training Data Enrichment** - Extend JSONL records with all Phase 5-6 fields, add run/step quality gates, and build the LoRA training scaffold (converter + two training scripts)
- [ ] **Phase 9: Frontend Polish** - Wire all new SSE events to the web UI: token/cost ticker, collapsible thought blocks, action type badges, expandable run history

## Phase Details

### Phase 5: Token Counting + Timing
**Goal**: Every agent step emits timing and token data — the pipeline knows how long each step took and how many tokens it consumed
**Depends on**: Phase 4
**Requirements**: PERF-01, PERF-02, PERF-04
**Success Criteria** (what must be TRUE):
  1. A `TokenEvent` appears in the SSE stream for each completed step, carrying `prompt_tokens`, `completion_tokens`, and `cost_usd` (API providers) or explicit nulls (Ollama)
  2. Each narration entry in the event stream includes `step_duration_ms` derived from `time.monotonic()` delta
  3. The active provider and model name are emitted once on run start and visible in SSE events
  4. Ollama steps emit `null` for token/cost fields (not `0` or empty string) — no `TypeError` on `Optional[float]` cost
**Plans:** 2 plans
- [x] 05-01-PLAN.md — Add TokenEvent/ModelInfoEvent + step_duration_ms to agent/events.py; author full Phase 5 RED test suite
- [x] 05-02-PLAN.md — Wire agent/runner.py: timing closure, _resolve_model_name, log_step token dict, _log_step TokenEvent emission, ModelInfoEvent at run start, calculate_cost=True

### Phase 6: Model Transparency
**Goal**: The model's evaluation of the previous step, its stated next goal, and rich action labels are extracted from `AgentOutput` and emitted as discrete SSE events before each action executes
**Depends on**: Phase 5
**Requirements**: TRANS-01, TRANS-02, TRANS-03
**Success Criteria** (what must be TRUE):
  1. A `ThoughtEvent` fires before each action via `register_new_step_callback`, carrying `thinking`, `evaluation_previous_goal`, `next_goal`, and `memory` fields
  2. An `ActionDetailEvent` carries `action_type`, `target`, `value`, `url`, and `success` — replacing the flat "Step N: click" label
  3. The step counter increments correctly server-side and is included in the SSE event payload
  4. `ThoughtEvent` fields are `null` (not missing keys) when the model returns no thought text
**Plans:** 2 plans
- [x] 06-01-PLAN.md — Author Phase 6 RED test suite (ThoughtEvent + ActionDetailEvent contract, _pre_step wiring, NarrationEvent-removal regression)
- [x] 06-02-PLAN.md — Wire ThoughtEvent + ActionDetailEvent dataclasses, _pre_step closure, register_new_step_callback on Agent, replace NarrationEvent emission, update Phase 5 tests

### Phase 7: Screenshot Streaming
**Goal**: Screenshots update approximately every 500ms during action execution — the displayed image is never more than one capture interval behind the live browser state
**Depends on**: Phase 6
**Requirements**: SCR-01, SCR-02
**Success Criteria** (what must be TRUE):
  1. A background `asyncio.Task` runs `browser.take_screenshot()` on a ~500ms interval during agent execution and pushes JPEG (quality=75) frames into the SSE queue
  2. The screenshot queue is bounded (`maxsize=50`); overflow frames are dropped with `put_nowait` rather than blocking the agent loop
  3. The screenshot task is cancelled before `browser.kill()` — no `TargetClosedError` hangs the `DoneEvent`
  4. Under a 20-step test run, the displayed screenshot is never more than one step behind the agent's actual browser state
**Plans:** 2 plans
- [x] 07-01-PLAN.md — Author Phase 7 RED test suite (12 tests for SCR-01/SCR-02: 500ms loop, JPEG q=75, QueueFull drop, exception/timeout continuation, cancel-before-kill ordering, _log_step ScreenshotEvent removal, Queue(maxsize=50))
- [x] 07-02-PLAN.md — Implement _screenshot_loop closure + task lifecycle in agent/runner.py; bound queue in agent/main.py; remove step-end ScreenshotEvent; turn the RED suite GREEN
**UI hint**: yes

### Phase 8: Training Data Enrichment
**Goal**: Every JSONL step record carries the full set of fields needed for LoRA fine-tuning, with quality gates that prevent failed runs from poisoning training data; converter and training scripts are ready to run
**Depends on**: Phase 7
**Requirements**: TRAIN-01, TRAIN-02, TRAIN-03, TRAIN-04, TRAIN-05, TRAIN-06
**Success Criteria** (what must be TRUE):
  1. Each JSONL step record contains: `step_duration_ms`, `prompt_tokens`, `completion_tokens`, `cost_usd`, `model_thought`, `evaluation_previous_goal`, `next_goal`, `provider`, `model_name`, `run_success`, `step_quality`
  2. Token and thought fields are populated only when `provider` is `anthropic` or `openai`; Ollama steps write explicit `null` for those fields
  3. `run_success` is written to all steps of a session at run completion (not per-step); `step_quality` is one of `clean | partial | failed`
  4. `training/converter.py` converts `runs.jsonl` to conversation-format JSONL (user turn: task + screenshot, assistant turn: thought + action) consumable by both Unsloth and mlx-vlm
  5. `training/train_nvidia.py` auto-detects VRAM, applies QLoRA 4-bit when < 16GB, and emits a human-readable OOM message rather than crashing silently
  6. `training/train_apple.py` targets the 3B model variant on Apple Silicon and auto-selects the mlx-vlm path
**Plans:** 2 plans
- [x] 08-01-PLAN.md — Author Phase 8 RED test suite (TRAIN-01..06 + CR-01/CR-02 regressions) and create training/__init__.py
- [x] 08-02-PLAN.md — Wire enriched JSONL + run_success back-fill + CR-01/CR-02 in agent/runner.py; implement training/converter.py + train_nvidia.py + train_apple.py; turn the RED suite GREEN

### Phase 9: Frontend Polish
**Goal**: All new SSE events are wired to observable UI elements — users see token counts, cost totals, collapsible thought blocks, action type badges, and expandable run history rows without page reloads
**Depends on**: Phase 8
**Requirements**: PERF-03, UI-01, UI-02
**Success Criteria** (what must be TRUE):
  1. A token/cost ticker in the UI header updates live during a run, showing "in: X / out: Y" tokens and "~$0.04" cumulative cost (or "local (no API cost)" for Ollama)
  2. Each narration entry includes a `<details>`/`<summary>` block for the model's thought text — collapsed by default, expandable with a click, rendered with no JavaScript framework
  3. Each narration entry shows a color-coded action type badge (navigate=blue, click=green, type=yellow, scroll=gray) applied via CSS class
  4. Run history rows expand to show step count, total duration, total cost, and model used for that run
  5. Screenshot JPEG blobs use `URL.createObjectURL` + `revokeObjectURL` via Alpine.js — no base64 string accumulation in the DOM
**Plans:** 2 plans
- [x] 09-01-PLAN.md — Author Phase 9 RED test suite (16 tests covering PERF-03/UI-01/UI-02 + Blob lifecycle); optional `jsonl_with_records` conftest fixture
- [x] 09-02-PLAN.md — Wire /runs aggregator + CSS rules + runs_fragment <details> wrap + index.html SSE bridges/handlers/header ticker/Blob screenshot rewrite; turn the RED suite GREEN
**UI hint**: yes

## Progress

| Phase | Milestone | Plans Complete | Status | Completed |
|-------|-----------|----------------|--------|-----------|
| 1. Scaffold + Core Loop PoC | v0.1.0 | 3/3 | Complete | 2026-05-13 |
| 2. Multi-Provider + Guardrails | v0.1.0 | 2/2 | Complete | 2026-05-15 |
| 3. Full Web UI | v0.1.0 | 3/3 | Complete | 2026-05-16 |
| 4. Distribution | v0.1.0 | 2/2 | Complete | 2026-05-16 |
| 5. Token Counting + Timing | v0.2.0 | 0/2 | Not started | — |
| 6. Model Transparency | v0.2.0 | 0/2 | Not started | — |
| 7. Screenshot Streaming | v0.2.0 | 0/2 | Not started | — |
| 8. Training Data Enrichment | v0.2.0 | 0/2 | Not started | — |
| 9. Frontend Polish | v0.2.0 | 0/2 | Not started | — |
</content>

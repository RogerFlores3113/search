# Requirements: v0.2.0 Foundations — local-browser-agent

**Defined:** 2026-05-16
**Milestone goal:** Harden the core loop — instrument performance, surface model transparency, fix screenshot lag, and build the training data pipeline before expanding features.

---

## Performance & Observability

- [x] **PERF-01**: User sees per-step elapsed time next to each narration entry (e.g., "3.2s")
- [ ] **PERF-02**: User sees token counts per step (prompt / completion tokens) — API providers only; "N/A" displayed for Ollama
- [ ] **PERF-03**: User sees cumulative cost for the run displayed as "~$0.04" — API providers only; "local (no API cost)" for Ollama
- [ ] **PERF-04**: User sees active model name and provider displayed in the UI during a run

## Model Transparency

- [ ] **TRANS-01**: User sees the model's evaluation of the previous step in the narration feed (collapsed `<details>` block by default, expandable)
- [ ] **TRANS-02**: User sees the model's stated next goal surfaced before each action executes
- [ ] **TRANS-03**: User sees richer action labels showing action type + target element (e.g., "Clicking: Search button" not "Step 3: click")

## Screenshot Streaming

- [ ] **SCR-01**: Screenshots update approximately every 500ms during action execution, not only on step completion
- [ ] **SCR-02**: Screenshot delivery lag is eliminated — the displayed screenshot is never more than one step behind the current agent state

## Training Data

- [x] **TRAIN-01**: Training JSONL record per step includes: `step_duration_ms`, `prompt_tokens`, `completion_tokens`, `cost_usd`, `model_thought`, `evaluation_previous_goal`, `next_goal`, `provider`, `model_name`
- [x] **TRAIN-02**: Enriched token/thought fields are populated only when provider is `anthropic` or `openai`; Ollama steps record `null` for those fields (not "0" or empty string)
- [x] **TRAIN-03**: Each JSONL step record includes `run_success` (written at run completion) and `step_quality: clean | partial | failed`
- [x] **TRAIN-04**: `training/converter.py` converts `runs.jsonl` to conversation-format JSONL (user turn: [task text + screenshot image], assistant turn: thought + action) consumable by Unsloth and mlx-vlm
- [x] **TRAIN-05**: `training/train_nvidia.py` — QLoRA fine-tuning scaffold for Qwen2.5-VL:7b on NVIDIA; auto-detects VRAM and applies 4-bit quantization when < 16GB; emits human-readable message on OOM
- [x] **TRAIN-06**: `training/train_apple.py` — mlx-vlm LoRA fine-tuning scaffold for Apple Silicon; uses 3B model variant; hardware path auto-selected by converter based on platform

## Frontend Polish

- [ ] **UI-01**: Narration feed shows color-coded action type badges per entry (e.g., navigate=blue, click=green, type=yellow, scroll=gray)
- [ ] **UI-02**: Run history rows are expandable to show step count, total duration, total cost, and model used for that run

---

## Future Requirements (deferred post-v0.2.0)

- Windows .exe distribution
- Full Apple notarization (Gatekeeper auto-pass)
- Manual smoke test sign-off (human with Chrome + Ollama)
- Structured task presets (apartment, job, lead search)
- Authenticated sessions + cookie persistence
- Excel/CSV export
- Full LoRA training run + evaluation benchmark (v0.3.0 — needs 500-1,000 quality steps captured first)
- Run replay / step-by-step playback
- Budget cap / cost alerting

---

## Out of Scope

- Cloud deployment — residential IP is a functional requirement; datacenter IPs blocked by target sites
- Electron wrapper — localhost UI in system browser is sufficient
- Headless browser — user's real Chrome (headed) avoids bot detection
- Per-domain scrapers / regex selectors — LLM vision handles arbitrary domains
- Multi-user / shared sessions — local single-user tool
- CAPTCHA auto-solving — pause and surface to user
- WebSockets — SSE + asyncio.Queue is sufficient for one-directional streaming
- GZipMiddleware on FastAPI — silently breaks SSE
- Actual fine-tuning run in v0.2.0 — data collection infrastructure first; training + evaluation is v0.3.0

---

## Traceability

| REQ-ID | Phase | Status |
|--------|-------|--------|
| PERF-01 | Phase 5 | Complete |
| PERF-02 | Phase 5 | Pending |
| PERF-04 | Phase 5 | Pending |
| TRANS-01 | Phase 6 | Pending |
| TRANS-02 | Phase 6 | Pending |
| TRANS-03 | Phase 6 | Pending |
| SCR-01 | Phase 7 | Pending |
| SCR-02 | Phase 7 | Pending |
| TRAIN-01 | Phase 8 | Complete |
| TRAIN-02 | Phase 8 | Complete |
| TRAIN-03 | Phase 8 | Complete |
| TRAIN-04 | Phase 8 | Complete |
| TRAIN-05 | Phase 8 | Complete |
| TRAIN-06 | Phase 8 | Complete |
| PERF-03 | Phase 9 | Pending |
| UI-01 | Phase 9 | Pending |
| UI-02 | Phase 9 | Pending |

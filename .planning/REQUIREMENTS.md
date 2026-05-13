# Requirements: local-browser-agent

**Defined:** 2026-05-13
**Core Value:** User types any natural language task, the agent opens Chrome and completes it — proving the general-purpose agentic loop works end-to-end before any structured presets are built.

## v1 Requirements

### Agent Loop

- [ ] **LOOP-01**: User enters a natural language task in the UI prompt box and submits it to start a run
- [x] **LOOP-02**: Agent runs a screenshot → LLM decision → browser action cycle via browser-use until the task is complete or a limit is reached
- [x] **LOOP-03**: Agent drives the user's installed Chrome browser (headed, visible, residential IP) for all browsing
- [x] **LOOP-04**: LLM has full browser control — click any element, type into any field, scroll, navigate to any URL
- [x] **LOOP-05**: Agent terminates automatically after a configurable `max_steps` limit (default: 25) to prevent infinite loops
- [x] **LOOP-06**: Agent terminates automatically after a configurable session timeout (default: 10 minutes)
- [ ] **LOOP-07**: User can pause the agent mid-run from the UI
- [ ] **LOOP-08**: User can stop the agent mid-run; Chrome closes cleanly with no orphan processes
- [ ] **LOOP-09**: Each agent step emits a plain-language narration event streamed live to the UI ("Navigating to Wikipedia...", "Clicking search button...", "Found result — extracting...")
- [ ] **LOOP-10**: Agent returns a plain-language summary of what it accomplished at the end of each run

### Model Support

- [x] **MODEL-01**: User can select Ollama as the AI provider; any installed Ollama vision model is accepted; Qwen2.5-VL:7b is the recommended default shown in the UI
- [ ] **MODEL-02**: User can select Anthropic (Claude) as the AI provider by entering an API key; key is stored locally only, never transmitted anywhere except Anthropic's API
- [ ] **MODEL-03**: User can select OpenAI (GPT-4o) as the AI provider by entering an API key; key is stored locally only, never transmitted anywhere except OpenAI's API
- [x] **MODEL-04**: App validates the selected model is reachable before starting a run; shows a clear, actionable error message if not (e.g., "Ollama is not running — start it with `ollama serve`")

### Guardrails

- [ ] **GUARD-01**: A configurable global domain blocklist prevents the agent from loading pages on restricted domains (banking sites, payment processors); blocked navigations are logged and surfaced to the user
- [ ] **GUARD-02**: Agent is instructed via system prompt not to click "Buy Now", "Purchase", "Checkout", "Pay", or equivalent CTAs on e-commerce or financial sites
- [ ] **GUARD-03**: Agent is instructed not to submit credentials, payment info, or personal data on any site the user did not explicitly name in the task prompt
- [ ] **GUARD-04**: If a CAPTCHA is detected, the agent pauses and notifies the user in the UI; the run does not fail silently and does not attempt auto-solving

### Live UI

- [ ] **UI-01**: User enters a natural language task in a prompt box and presses Enter (or clicks Run) to start the agent
- [ ] **UI-02**: The agent's current browser viewport is captured at each step and streamed to the UI so the user can see exactly what the agent sees
- [ ] **UI-03**: A live narration feed shows a plain-language description of each action as it happens, updating in real time via SSE
- [ ] **UI-04**: UI shows the current agent state at all times: idle / running / paused / complete / error
- [ ] **UI-05**: UI shows a progress indicator: steps taken vs. max steps, and elapsed time — both updating live
- [ ] **UI-06**: Pause button halts the agent mid-step; Resume continues from where it stopped
- [ ] **UI-07**: Stop button terminates the agent immediately and closes the browser cleanly
- [ ] **UI-08**: Failed runs display a plain-language error message — not a Python stack trace
- [ ] **UI-09**: Completed runs display the agent's plain-language summary of what it accomplished

### Run History & Training Data

- [ ] **RUN-01**: Each run's task prompt, narration log, final summary, and status are saved locally on completion
- [ ] **RUN-02**: User can view a list of recent runs showing: task prompt (truncated), status, and timestamp
- [ ] **RUN-03**: Every agent step is logged as a training record: `{screenshot_b64, action_type, action_target, action_value, narration, step_success}` saved to a local JSONL file — foundation for future LoRA/DPO fine-tuning of local models

### Distribution

- [ ] **DIST-01**: User can launch the app on Mac by double-clicking a `.app` bundle — no Python, no terminal, no SDK required
- [ ] **DIST-02**: App detects the user's installed Google Chrome and drives it via `channel="chrome"`; if Chrome is not found, a friendly prompt explains what to install
- [ ] **DIST-03**: App opens the user's default browser to `localhost:8080` automatically within 3 seconds of launch
- [ ] **DIST-04**: First-time users see a one-time safety disclaimer before any run starts — explaining what the agent can do, what it won't do, and that it acts on their behalf
- [ ] **DIST-05**: GitHub Actions pipeline builds and publishes the `.app` to GitHub Releases automatically on each version tag push

---

## v2 Requirements

### Structured Task Presets

- **PRESET-01**: Apartment search preset — structured form (city, price, beds, sources); output schema with address/price/beds/baths/URL; SQLite storage per run
- **PRESET-02**: Job search preset — structured form; requires authenticated session design
- **PRESET-03**: Candidate/lead search preset
- **PRESET-04**: Preset YAML system — user-editable, validated against Pydantic schema
- **PRESET-05**: Preset editor GUI in the UI

### Output & Export

- **OUT-01**: Structured results saved to SQLite per run (for preset-driven tasks)
- **OUT-02**: One-click Excel (.xlsx) export of run results
- **OUT-03**: One-click CSV export of run results
- **OUT-04**: httpx fast-path executor for non-JS sites (Craigslist, Zumper) — skip LLM tokens for static pages

### Authenticated Sessions

- **AUTH-01**: User can save named credential sets in encrypted local storage
- **AUTH-02**: Agent can log in to a site using a stored credential set when the task requires it
- **AUTH-03**: Session cookies persisted between runs for the same account

### Platform Ports

- **PLAT-01**: Windows `.exe` installer via GitHub Actions
- **PLAT-02**: Linux AppImage or `uv` launch script

### Power Features

- **PWR-01**: Voice dictation for task prompt input
- **PWR-02**: Run history with screenshot-by-screenshot replay
- **PWR-03**: Agent performance metrics (tokens used, cost estimate per run)
- **PWR-04**: LoRA/DPO fine-tuning pipeline — use collected training JSONL to fine-tune Qwen2.5-VL on domain-specific browsing behavior; ship tuned model to family/friends
- **PWR-05**: Training data review UI — browse collected (screenshot, action, outcome) pairs, flag bad examples, export curated dataset

---

## Out of Scope

| Feature | Reason |
|---------|--------|
| Per-domain regex/selector scrapers | Obsolete — LLM vision handles arbitrary domains; building per-domain logic is regressing to pre-LLM tooling |
| Cloud deployment | Residential IP is a functional requirement; datacenter IPs get blocked by real-world sites |
| Headless browser | Headed Chrome avoids bot detection fingerprinting; headless is technically inferior |
| Using the user's existing Chrome profile | Risk of corrupting active sessions; agent runs its own isolated Chrome instance |
| CAPTCHA auto-solving | Legal grey area; user handles manually via handoff |
| Electron wrapper | Unnecessary overhead; PyInstaller/Briefcase achieves the same result |
| Docker distribution | Incompatible with headed browser requirement |
| Any automatic form submission | Safety guardrail — agent reads and navigates, user decides when to act |

---

## Traceability

| Requirement | Phase | Status |
|-------------|-------|--------|
| LOOP-02 | Phase 1 | Complete |
| LOOP-03 | Phase 1 | Complete |
| LOOP-04 | Phase 1 | Complete |
| LOOP-05 | Phase 1 | Complete |
| LOOP-06 | Phase 1 | Complete |
| MODEL-01 | Phase 1 | Complete |
| MODEL-04 | Phase 1 | Complete |
| MODEL-02 | Phase 2 | Pending |
| MODEL-03 | Phase 2 | Pending |
| GUARD-01 | Phase 2 | Pending |
| GUARD-02 | Phase 2 | Pending |
| GUARD-03 | Phase 2 | Pending |
| GUARD-04 | Phase 2 | Pending |
| LOOP-01 | Phase 3 | Pending |
| LOOP-07 | Phase 3 | Pending |
| LOOP-08 | Phase 3 | Pending |
| LOOP-09 | Phase 3 | Pending |
| LOOP-10 | Phase 3 | Pending |
| UI-01 | Phase 3 | Pending |
| UI-02 | Phase 3 | Pending |
| UI-03 | Phase 3 | Pending |
| UI-04 | Phase 3 | Pending |
| UI-05 | Phase 3 | Pending |
| UI-06 | Phase 3 | Pending |
| UI-07 | Phase 3 | Pending |
| UI-08 | Phase 3 | Pending |
| UI-09 | Phase 3 | Pending |
| RUN-01 | Phase 3 | Pending |
| RUN-02 | Phase 3 | Pending |
| RUN-03 | Phase 3 | Pending |
| DIST-01 | Phase 4 | Pending |
| DIST-02 | Phase 4 | Pending |
| DIST-03 | Phase 4 | Pending |
| DIST-04 | Phase 4 | Pending |
| DIST-05 | Phase 4 | Pending |

**Coverage:**
- v1 requirements: 35 total
- Mapped to phases: 34
- Unmapped: 0 ✓

---
*Requirements defined: 2026-05-13*
*Last updated: 2026-05-13 — rewritten to general-purpose agent scope (no per-domain presets in v1)*

# Roadmap: local-browser-agent

## Milestones

- ✅ **v0.1.0 MVP** — Phases 1-4 (shipped 2026-05-16)
- ✅ **v0.2.0 Foundations** — Phases 5-9.1 (shipped 2026-05-18)
- 📋 **v0.3.0 Polish & Presets** — Phases 10-15 (planned)

## Phases

<details>
<summary>✅ v0.1.0 MVP (Phases 1-4) — SHIPPED 2026-05-16</summary>

- [x] Phase 1: Scaffold + Core Loop PoC (3/3 plans) — completed 2026-05-13
- [x] Phase 2: Multi-Provider + Guardrails (2/2 plans) — completed 2026-05-15
- [x] Phase 3: Full Web UI (3/3 plans) — completed 2026-05-16
- [x] Phase 4: Distribution (2/2 plans) — completed 2026-05-16

See archive: `.planning/milestones/v0.1.0-ROADMAP.md`

</details>

<details>
<summary>✅ v0.2.0 Foundations (Phases 5-9.1) — SHIPPED 2026-05-18</summary>

- [x] Phase 5: Token Counting + Timing (2/2 plans) — completed 2026-05-17
- [x] Phase 6: Model Transparency (2/2 plans) — completed 2026-05-17
- [x] Phase 7: Screenshot Streaming (2/2 plans) — completed 2026-05-17
- [x] Phase 8: Training Data Enrichment (2/2 plans) — completed 2026-05-18
- [x] Phase 9: Frontend Polish (2/2 plans) — completed 2026-05-18
- [x] Phase 9.1: Close gap PERF-01 — wire step_duration_ms (2/2 plans) — completed 2026-05-18

See archive: `.planning/milestones/v0.2.0-ROADMAP.md`

</details>

### 📋 v0.3.0 Polish & Presets (Planned)

**Milestone Goal:** Make the app portfolio-ready — fix all visual rendering gaps, add a settings panel with Ollama model discovery, domain safety, and prompt library, build task presets with deep domain-tuned prompts, and ship Windows .exe packaging.

- [x] **Phase 10: UI Rendering Fixes + Theme** - Fix all v0.2.0 visual gaps and apply dark-green theme, badge colors, real-time status spinner, and compressed layout (completed 2026-05-19)
- [x] **Phase 11: Settings Panel + Domain Safety** - Settings drawer with Ollama model discovery, API key storage, provider selector, and two-tier domain exclusion list (completed 2026-05-19)
- [x] **Phase 12: Prompt Library** - Full CRUD prompt library with named saves, active selection, locked seed prompts, and GUARDRAIL_PROMPT suffix enforcement (completed 2026-05-18)
- [x] **Phase 13: Task Presets + Prompt Engineering + Runner Wiring** - Three task preset buttons wiring to domain-tuned prompts; deep engineered system prompts for all four use cases; runner config snapshot (completed 2026-05-19)
- [ ] **Phase 14: Windows Distribution** - PyInstaller .exe build with Windows Chrome detection, freeze_support, and GitHub Actions CI artifact
- [ ] **Phase 15: Portfolio Presentation** - README screenshots/GIF, download story for Mac and Windows, architecture overview

## Phase Details

### Phase 10: UI Rendering Fixes + Theme
**Goal**: The running app looks correct and polished — all v0.2.0 visual rendering gaps fixed and the full dark-green theme, badge colors, and status layout applied
**Depends on**: Phase 9.1 (v0.2.0 complete)
**Requirements**: FIX-01, FIX-02, FIX-03, FIX-04, THEME-01, THEME-02, THEME-03, THEME-04, THEME-05
**Success Criteria** (what must be TRUE):
  1. Each step row in the log shows its duration (e.g. "2.3s") and an action badge (Click / Type / Scroll / Navigate) correctly rendered
  2. The token count and cost ticker update live during an active run with each new step
  3. Run history rows expand and collapse correctly when clicked
  4. The entire UI surface uses a dark green color scheme; action badges are blue, error badges red, DONE badge green
  5. A one-liner agent status ("Thinking..." / "Clicking..." / "Typing...") with a spinner is visible above the step log; thought/reasoning blocks appear below the agent screenshot area; step log is compressed
**Plans**: 3 plans
  - [x] 10-01-PLAN.md — Wave 0 test scaffolding: create test_events_phase10.py with 14 RED assertions; update test_events_phase9.py palette test
  - [x] 10-02-PLAN.md — CSS changes in agent/static/style.css: dark-green :root tokens, unified blue action badges, narration-row alignment fix, timestamp contrast fix, run-history chevron, spinner keyframe + .spinner, .agent-status, .thought-area, compressed narration layout
  - [x] 10-03-PLAN.md — HTML + Alpine changes in agent/templates/index.html: insert #thought-area + .agent-status DOM, add currentAction prop + agentStatusText() method, rewire handleActionDetail/handleState/handleThought, add modelName fallback in handleToken
**UI hint**: yes

### Phase 11: Settings Panel + Domain Safety
**Goal**: Users can open a settings panel from the main UI and configure their LLM provider, model, API keys, and domain exclusion list — all persisted across launches
**Depends on**: Phase 10
**Requirements**: SET-01, SET-02, SET-03, SET-04, SAFE-01, SAFE-02, SAFE-03, SAFE-04
**Success Criteria** (what must be TRUE):
  1. User can open a settings panel from the main UI (gear icon or menu) and close it without losing progress
  2. Settings panel shows a live-discovered list of Ollama models fetched from the local Ollama API; user can select one
  3. User can enter and save Anthropic and OpenAI API keys via masked input fields; keys persist across app restarts (stored via settings.json, never plaintext SQLite)
  4. User can select the active LLM provider (Ollama / Anthropic / OpenAI) from the settings panel
  5. Domain exclusion list is pre-filled with banking, payment, government, medical, and credential defaults that cannot be removed; user can add and remove their own additional domains
**Plans**: 4 plans
  - [x] 11-01-PLAN.md — Wave 0 scaffolding: cryptography dep, get_settings_path(), agent/settings.py Fernet+JSON I/O, test_settings_phase11.py RED scaffold, pydantic mutability verification, CVE-2025-47241 test
  - [x] 11-02-PLAN.md — Refactor agent/config.py: SAFETY_DEFAULTS frozenset (banking/payment/government/medical/credential), user_domains field, blocked_domains property, JsonConfigSettingsSource; wire runner.py two-tier merge
  - [x] 11-03-PLAN.md — FastAPI routes in agent/main.py: GET /api/settings (sanitized), GET /api/settings/ollama-models (httpx proxy), POST /api/settings (encrypt+persist+live-patch, disclaimer-gated)
  - [x] 11-04-PLAN.md — UI in agent/templates/index.html + agent/static/style.css: gear icon, settings overlay (role=dialog), provider radios, key inputs, two-tier domain list, Save with confirmation
**UI hint**: yes

### Phase 12: Prompt Library
**Goal**: Users can manage named system prompts, select an active prompt for the next run, and be protected by an always-on GUARDRAIL_PROMPT suffix that is never user-editable
**Depends on**: Phase 11
**Requirements**: PROMPT-01, PROMPT-02, PROMPT-03, PROMPT-04, PROMPT-05, PROMPT-06, PROMPT-07
**Success Criteria** (what must be TRUE):
  1. User can view all saved system prompts in the settings panel and see which one is currently active
  2. User can create a new named system prompt, edit an existing one, and delete user-created prompts
  3. On first init the app seeds four named prompts (Generic, Apartment Search, Job Search, Candidate Search) that can be edited but not deleted from the UI
  4. User can select any prompt as the active prompt; the active prompt indicator is visible near the task input on the main UI
  5. GUARDRAIL_PROMPT is appended as a non-editable suffix after every user-selected prompt at run time; it does not appear in the prompt editor
**Plans**: 4 plans
  - [x] 12-01-PLAN.md — Wave 0 TDD scaffolding: 12 RED test stubs in tests/unit/test_prompts_phase12.py covering PROMPT-01–07
  - [x] 12-02-PLAN.md — Wave 1 backend: Settings fields, SEED_PROMPTS + seed_prompts_if_absent, _build_extend_system_message in runner.py, GET/POST /api/settings + lifespan seeding
  - [x] 12-03-PLAN.md — Wave 2 frontend: Prompts section in settings overlay, active-prompt label below task input, Alpine state + methods, Phase 12 CSS classes
  - [x] 12-04-PLAN.md — Wave 3 green/UAT: full suite green, human UAT of 5 ROADMAP success criteria, SUMMARY + ROADMAP/REQUIREMENTS/STATE updates
**UI hint**: yes

### Phase 13: Task Presets + Prompt Engineering + Runner Wiring
**Goal**: Users can launch structured searches with one click from preset buttons; each preset pre-fills the task and activates a deep domain-tuned system prompt; the runner correctly reads and freezes config at task-start
**Depends on**: Phase 12
**Requirements**: PRESET-01, PRESET-02, PRESET-03, ENG-01, ENG-02, ENG-03, ENG-04
**Success Criteria** (what must be TRUE):
  1. Three preset buttons (Apartment Search, Job Search, Candidate Search) are visible on the main UI; clicking one pre-fills the task input with an editable template
  2. Selecting a preset automatically activates its corresponding domain-tuned system prompt (confirmed by the active prompt indicator updating)
  3. All four system prompts (Generic, Apartment, Job, Candidate) contain detailed numbered step sequences, explicit stop conditions, field extraction schemas, and time/cost awareness guidance
  4. Runner snapshots active provider, model, and prompt at task-start — mid-run settings changes do not affect the current task; prompt_id is recorded on the run history row
**Plans**: 4 plans
  - [x] 13-01-PLAN.md — Wave 0 RED scaffold: 12 failing tests in tests/unit/test_presets_phase13.py covering PRESET-01..03, ENG-01..04, runner snapshot, DB migration
  - [x] 13-02-PLAN.md — SEED_PROMPTS body expansion in agent/settings.py for ENG-01..04 (Generic, Apartment, Job unauthenticated-only, Candidate)
  - [x] 13-03-PLAN.md — Backend wiring: prompt_id column migration, runner snapshot + CR-01 fix, /run endpoint active_prompt_id Form field
  - [x] 13-04-PLAN.md — Frontend: preset row, applyPreset() Alpine method, .btn-preset CSS, runs_fragment prompt_id display

### Phase 14: Windows Distribution
**Goal**: The app builds and runs as a double-click Windows .exe; GitHub Actions produces a Windows artifact on every tag push alongside the existing Mac .app
**Depends on**: Phase 13 (independent track — can parallelize with Phase 13 if bandwidth allows)
**Requirements**: WIN-01, WIN-02, WIN-03, WIN-04
**Success Criteria** (what must be TRUE):
  1. A double-click Windows .exe launches the app without requiring Python, uv, or any terminal interaction
  2. Windows build correctly detects Chrome via %LOCALAPPDATA%, %PROGRAMFILES%, and %PROGRAMFILES(X86)% paths
  3. Windows build includes multiprocessing.freeze_support() and routes stdout/stderr to a log file (no crash on console=False)
  4. GitHub Actions tag push produces both a Mac .app and a Windows .exe artifact on the GitHub Releases page
**Plans**: TBD

### Phase 15: Portfolio Presentation
**Goal**: The README tells a clear story for portfolio visitors — they can see the app running, understand the architecture, and download it on their OS
**Depends on**: Phase 14
**Requirements**: PORT-01, PORT-02, PORT-03
**Success Criteria** (what must be TRUE):
  1. README includes at least one screenshot or animated GIF showing the app completing a real task (agent loop visible)
  2. README includes clear step-by-step download and install instructions for both Mac and Windows
  3. README includes a concise architecture section that explains the browser-use + BYOM + HTMX/SSE stack in plain language
**Plans**: TBD

## Progress

| Phase | Milestone | Plans Complete | Status | Completed |
|-------|-----------|----------------|--------|-----------|
| 1. Scaffold + Core Loop PoC | v0.1.0 | 3/3 | Complete | 2026-05-13 |
| 2. Multi-Provider + Guardrails | v0.1.0 | 2/2 | Complete | 2026-05-15 |
| 3. Full Web UI | v0.1.0 | 3/3 | Complete | 2026-05-16 |
| 4. Distribution | v0.1.0 | 2/2 | Complete | 2026-05-16 |
| 5. Token Counting + Timing | v0.2.0 | 2/2 | Complete | 2026-05-17 |
| 6. Model Transparency | v0.2.0 | 2/2 | Complete | 2026-05-17 |
| 7. Screenshot Streaming | v0.2.0 | 2/2 | Complete | 2026-05-17 |
| 8. Training Data Enrichment | v0.2.0 | 2/2 | Complete | 2026-05-18 |
| 9. Frontend Polish | v0.2.0 | 2/2 | Complete | 2026-05-18 |
| 9.1. Close gap PERF-01 | v0.2.0 | 2/2 | Complete | 2026-05-18 |
| 10. UI Rendering Fixes + Theme | v0.3.0 | 3/3 | Complete    | 2026-05-19 |
| 11. Settings Panel + Domain Safety | v0.3.0 | 5/5 | Complete   | 2026-05-19 |
| 12. Prompt Library | v0.3.0 | 4/4 | Complete    | 2026-05-19 |
| 13. Task Presets + Prompt Engineering + Runner Wiring | v0.3.0 | 3/4 | In Progress|  |
| 14. Windows Distribution | v0.3.0 | 0/? | Not started | — |
| 15. Portfolio Presentation | v0.3.0 | 0/? | Not started | — |

# Requirements: local-browser-agent

**Defined:** 2026-05-18
**Milestone:** v0.3.0 Polish & Presets
**Core Value:** User types any natural language task, the agent opens Chrome and completes it — a general-purpose agentic loop that works on arbitrary sites before structured presets are layered on top.

## v0.3.0 Requirements

### UI Rendering Fixes

- [x] **FIX-01**: User sees per-step duration ("2.3s") rendered correctly next to each step in the log
- [x] **FIX-02**: User sees token count and cost ticker update live during a run
- [x] **FIX-03**: User sees action badges (click / type / scroll / navigate) displayed on each step row
- [x] **FIX-04**: User sees run history panel expand/collapse correctly

### UI Theme & Layout

- [x] **THEME-01**: App uses a dark green color scheme (replacing black/grey) throughout all UI surfaces
- [x] **THEME-02**: Action badges are blue; error badges are red; DONE badge is green
- [x] **THEME-03**: User sees a real-time one-liner agent status ("Thinking…" / "Clicking…" / "Typing…") with a spinner, replacing verbose narration in the status area
- [x] **THEME-04**: Thought/reasoning blocks are rendered below the agent screenshot area
- [x] **THEME-05**: Step log is displayed in a compressed view below the status area

### Settings Panel

- [ ] **SET-01**: User can open a settings panel from the main UI
- [ ] **SET-02**: User can select a model from a live-discovered list of Ollama models (queried from local Ollama API at open time)
- [ ] **SET-03**: User can enter and save API keys for Anthropic and OpenAI (stored via keyring with Fernet fallback — never plaintext)
- [ ] **SET-04**: User can select the active LLM provider (Ollama / Anthropic / OpenAI) from the settings panel

### Domain Safety

- [ ] **SAFE-01**: App ships with a pre-filled domain exclusion list covering banking, payment processors, government, medical, and credential sites — these defaults cannot be removed from the UI
- [ ] **SAFE-02**: User can add additional domains to the exclusion list from the settings panel
- [ ] **SAFE-03**: User-added domains can be removed; default safety domains cannot
- [ ] **SAFE-04**: Domain exclusion list is verified against CVE-2025-47241 (URL auth-credential bypass) in browser-use 0.12.6 before shipping

### Prompt Library

- [x] **PROMPT-01**: User can view all saved system prompts in the settings panel — Validated by Phase 12
- [x] **PROMPT-02**: User can create a new named system prompt — Validated by Phase 12
- [x] **PROMPT-03**: User can edit an existing prompt — Validated by Phase 12
- [x] **PROMPT-04**: User can delete a prompt (except locked defaults) — Validated by Phase 12
- [x] **PROMPT-05**: User can select which prompt is active for the next run — Validated by Phase 12
- [x] **PROMPT-06**: App seeds 4 named prompts on first init: Generic, Apartment Search, Job Search, Candidate Search — user can edit but not delete these from the UI — Validated by Phase 12
- [x] **PROMPT-07**: GUARDRAIL_PROMPT is always appended as a suffix after the user-selected prompt — it is not user-editable or removable — Validated by Phase 12

### Task Presets

- [ ] **PRESET-01**: User can select a preset (Apartment Search / Job Search / Candidate Search) from the main UI
- [ ] **PRESET-02**: Selecting a preset pre-fills the task input with a template the user can edit before running
- [ ] **PRESET-03**: Each preset automatically activates its corresponding domain-tuned system prompt

### Prompt Engineering

- [ ] **ENG-01**: Generic system prompt provides detailed step-by-step agentic guidance — environment framing, numbered action sequences, explicit stop conditions, output schema, time/cost awareness
- [ ] **ENG-02**: Apartment search prompt provides domain-specific guidance for rental sites (Craigslist, Apartments.com, Zillow) — field extraction schema, pagination, duplicate detection, stop conditions
- [ ] **ENG-03**: Job search prompt provides domain-specific guidance for job boards (LinkedIn, Indeed) — filter application, result extraction schema, pagination, stop conditions
- [ ] **ENG-04**: Candidate/lead search prompt provides guidance for people research — source prioritization, profile field extraction, credibility signals, stop conditions

### Windows Distribution

- [ ] **WIN-01**: App builds as a double-click Windows `.exe` via PyInstaller (onedir mode, no UPX)
- [ ] **WIN-02**: Windows build includes `multiprocessing.freeze_support()` and stdout redirect for `console=False` mode
- [ ] **WIN-03**: Windows Chrome detection covers `%LOCALAPPDATA%`, `%PROGRAMFILES%`, and `%PROGRAMFILES(X86)%` paths
- [ ] **WIN-04**: GitHub Actions release pipeline produces a Windows `.exe` artifact on tag push alongside the existing Mac `.app`

### Portfolio Presentation

- [ ] **PORT-01**: README includes screenshots or animated GIF of the app running a real task
- [ ] **PORT-02**: README includes clear Mac and Windows download/install instructions
- [ ] **PORT-03**: README includes a concise architecture section explaining the browser-use + BYOM + HTMX/SSE stack

## Future Requirements

### Performance

- **PERF-05**: Fast path via httpx for non-JS sites (Craigslist, Zumper) — bypasses LLM for deterministic scraping
- **PERF-06**: Parallel agent runs for batch tasks (multiple cities, multiple job boards)

### Auth & Sessions

- **AUTH-02**: Optional persistent Chrome profile — user can opt into saving cookies/sessions across runs
- **AUTH-03**: Credential vault — user can store site-specific login credentials for authenticated agent runs

### Training

- **TRAIN-07**: LoRA fine-tuning run on accumulated JSONL data — requires 1,000+ quality steps
- **TRAIN-08**: Benchmark suite to evaluate fine-tuned model vs base on standard tasks

### Distribution

- **DIST-01**: Full Apple notarization (vs ad-hoc codesign) — required for Gatekeeper auto-pass on all Macs
- **DIST-02**: Auto-update mechanism — app checks for new releases on launch

## Out of Scope

| Feature | Reason |
|---------|--------|
| Cloud/hosted deployment | Datacenter IPs blocked by apartment/job/lead sites; residential IP is a functional requirement |
| Auth audit code changes | WSL Chrome launches isolated fresh profile — no credential access; documentation only |
| Voice dictation | Nice-to-have; deferred to v2 |
| CAPTCHA solving | Log and surface to user; solving is a dedicated feature requiring external service |
| Multi-user / shared sessions | Local single-user tool |
| Electron wrapper | Adds 200MB+, Node.js runtime, Chromium duplication; localhost in system browser is sufficient |
| Per-domain scrapers / regex selectors | Obsolete; LLM vision handles arbitrary domains |
| A/B prompt testing automation | Prompt library supports manual A/B by switching active prompt; automated A/B harness is v2 |
| keyring on headless Linux without fallback | Fernet fallback with secret.bin handles WSL headless case |

## Traceability

| Requirement | Phase | Status |
|-------------|-------|--------|
| FIX-01 | Phase 10 | Complete |
| FIX-02 | Phase 10 | Complete |
| FIX-03 | Phase 10 | Complete |
| FIX-04 | Phase 10 | Complete |
| THEME-01 | Phase 10 | Complete |
| THEME-02 | Phase 10 | Complete |
| THEME-03 | Phase 10 | Complete |
| THEME-04 | Phase 10 | Complete |
| THEME-05 | Phase 10 | Complete |
| SET-01 | Phase 11 | Pending |
| SET-02 | Phase 11 | Pending |
| SET-03 | Phase 11 | Pending |
| SET-04 | Phase 11 | Pending |
| SAFE-01 | Phase 11 | Pending |
| SAFE-02 | Phase 11 | Pending |
| SAFE-03 | Phase 11 | Pending |
| SAFE-04 | Phase 11 | Pending |
| PROMPT-01 | Phase 12 | Complete |
| PROMPT-02 | Phase 12 | Complete |
| PROMPT-03 | Phase 12 | Complete |
| PROMPT-04 | Phase 12 | Complete |
| PROMPT-05 | Phase 12 | Complete |
| PROMPT-06 | Phase 12 | Complete |
| PROMPT-07 | Phase 12 | Complete |
| PRESET-01 | Phase 13 | Pending |
| PRESET-02 | Phase 13 | Pending |
| PRESET-03 | Phase 13 | Pending |
| ENG-01 | Phase 13 | Pending |
| ENG-02 | Phase 13 | Pending |
| ENG-03 | Phase 13 | Pending |
| ENG-04 | Phase 13 | Pending |
| WIN-01 | Phase 14 | Pending |
| WIN-02 | Phase 14 | Pending |
| WIN-03 | Phase 14 | Pending |
| WIN-04 | Phase 14 | Pending |
| PORT-01 | Phase 15 | Pending |
| PORT-02 | Phase 15 | Pending |
| PORT-03 | Phase 15 | Pending |

**Coverage:**
- v0.3.0 requirements: 35 total
- Mapped to phases: 35 (Phases 10–15)
- Unmapped: 0 ✓

---
*Requirements defined: 2026-05-18*
*Last updated: 2026-05-18 after roadmap creation — all 35 requirements mapped*

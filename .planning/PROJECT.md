# local-browser-agent

## What This Is

A consumer-grade local AI browser agent — download, double-click, done. The app drives the user's own Chrome from their machine and residential IP, the LLM has full browser control (click, type, scroll, navigate), and every step streams live to a localhost web UI. User types any natural language task; the agent completes it on any site. No Python, no terminal, no cloud required.

## Core Value

User types any natural language task, the agent opens Chrome and completes it — a general-purpose agentic loop that works on arbitrary sites before structured presets are layered on top.

## Requirements

### Validated

- ✓ General-purpose agentic loop: screenshot → LLM decision → browser action → repeat (any site, any task) — v0.1.0
- ✓ LLM has full browser control: click, type, scroll, navigate — no per-domain logic — v0.1.0
- ✓ browser-use as the loop engine (Python-native, MIT, validated over raw Playwright) — v0.1.0
- ✓ BYOM: Ollama (local, Qwen2.5-VL:7b recommended), Anthropic (Claude), OpenAI (GPT-4o) — v0.1.0
- ✓ Guardrails: CDP domain blocklist + action system-prompt (no payment CTAs, no credential submission) — v0.1.0
- ✓ Localhost web UI: prompt box, live screenshot stream, narration feed, state/progress, pause/stop — v0.1.0
- ✓ Run history: task, status, timestamp saved locally; recent runs viewable — v0.1.0
- ✓ Training JSONL: every step logged with screenshot, action, narration — v0.1.0
- ✓ Mac .app distribution: double-click launch, no dependencies, drives user's Chrome — v0.1.0
- ✓ Safety disclaimer on first launch (Alpine.js + localStorage gate) — v0.1.0
- ✓ GitHub Actions release pipeline: tag push → build → codesign → GitHub Releases — v0.1.0
- ✓ Per-step latency timing: `step_duration_ms` wired through `_log_step` → `ActionDetailEvent` (PERF-01) — v0.2.0
- ✓ Token counting + cost estimation per step: `TokenEvent` SSE, `prompt_tokens`/`completion_tokens`/`cost_usd` (PERF-02, PERF-04) — v0.2.0
- ✓ ThoughtEvent + ActionDetailEvent SSE events via `register_new_step_callback` (TRANS-01, TRANS-02, TRANS-03) — v0.2.0
- ✓ Continuous JPEG screenshot streaming via background asyncio task, queue bounded at maxsize=50 (SCR-01, SCR-02) — v0.2.0
- ✓ Enriched training JSONL: step_duration_ms, tokens, cost, model_thought, provider, model_name, run_success, step_quality (TRAIN-01–03) — v0.2.0
- ✓ LoRA training scaffold: converter.py + train_nvidia.py (QLoRA 4-bit auto) + train_apple.py (mlx-vlm 3B) (TRAIN-04–06) — v0.2.0
- ✓ Frontend polish: token/cost ticker, action badges, collapsible thought blocks, expandable run history, Blob screenshot lifecycle (PERF-03, UI-01, UI-02) — v0.2.0 (visual rendering deferred to v0.3.0 refactor)
- ✓ UI rendering fixes + theme refactor: dark-green tokens, unified blue badges, narration compression, timestamp/chevron fixes, spinner + thought-area + agent-status wired (FIX-01–04, THEME-01–05) — v0.3.0 Phase 10 (visual UAT pending)

### Active (v0.3.0)

- [x] UI theme overhaul: dark green color scheme, blue action badges, red errors, green DONE (UI-THEME-01) — Phase 10
- [x] Real-time agent status: one-liner "thinking" / "clicking" / "typing" + spinner, replacing verbose narration (UI-STATUS-01) — Phase 10
- [x] Thought blocks rendered below agent screen; compressed step log below status area (UI-LAYOUT-01) — Phase 10
- [x] Visual rendering gaps fixed: step duration, token/cost ticker, action badges, run history (UI-FIX-01) — Phase 10
- [ ] Settings panel: Ollama model auto-discovery, API key inputs, domain exclusion list, prompt library (SET-01–04)
- [ ] Domain exclusion list: pre-filled safety defaults (banking, payment, gov, medical) — some non-editable, user-extensible (SAFE-01)
- [ ] Prompt library: save/name multiple system prompts, select active, enable A/B testing (PROMPT-01)
- [x] Task presets: apartment, job, candidate search — pre-filled templates with per-preset domain-tuned prompts (PRESET-01, PRESET-02, PRESET-03) — Phase 13
- [x] Deep prompt engineering: generic + apartment + job (unauthenticated-only) + candidate system prompts, runner snapshot (ENG-01–04) — Phase 13
- [ ] Auth & browser isolation audit: determine WSL Chrome credential posture, document findings (AUTH-01)
- [ ] Windows .exe packaging: PyInstaller .exe, double-click to run, GitHub Actions tag → release (WIN-01)
- [ ] Portfolio presentation: README with screenshots/GIF, Mac + Windows download story (PORTFOLIO-01)

### Out of Scope

- Cloud deployment — datacenter IPs get blocked by apartment/job/lead sites; residential IP is a functional requirement, not just a privacy preference
- Electron wrapper — adds complexity; localhost UI in the system browser is sufficient
- Headless browser — the app uses the user's real Chrome (headed), which avoids bot detection and is the better UX; headless mode not needed
- Authenticated sessions (login, saved credentials) in v1 — apartment search is unauthenticated; credential management is a dedicated v2 feature requiring secure storage design
- Using the user's existing browser — too risky; could corrupt active sessions; agent runs its own isolated Chrome instance
- CAPTCHA solving — not a v1 concern; log and surface to user when encountered
- Multi-user or shared sessions — local single-user tool
- Per-domain scrapers / regex selectors — obsolete; LLM vision handles arbitrary domains
- Fast path (httpx) in v1 — v2 performance optimization once the general agent loop is solid
- Voice dictation in v1 — nice-to-have for search input, deferred to v2

## Context

**Prior art — Selenium leads finder:** Built by the developer, broke on JS-heavy pages, dynamic content, CAPTCHAs, and brittle CSS selectors. Motivation for the current approach: vision-driven LLM navigation has no selectors to break, and handles dynamic pages by seeing them as a human does.

**Prior art — Podium:** Developer's BYOK webapp LLM assistant with agentic loops. Architecture reference for the BYOM pattern and provider abstraction.

**Prior art — Apartment finder webapp:** Existing separate repo with live demo. Scraper logic (Craigslist, Zumper via httpx) will be ported as the fast-path for non-JS sites in the apartment preset. The browser agent handles JS-rendered pages where httpx falls short.

**Hardware reality:** Apple Silicon Macs (M1/M2/M3/M4, 16GB+) are tier-1 for local Ollama inference (Metal GPU acceleration, unified memory). NVIDIA RTX 3060 12GB+ on Windows is also excellent. Intel/AMD integrated users should use API providers (Anthropic/OpenAI/Gemini) — the BYOM architecture is the escape hatch for weaker hardware.

**Why local-first:** Residential IP avoids datacenter IP blocks on apartment/job/lead sites. Cloud deployment was evaluated and abandoned for this reason. The browser runs on the user's machine from their IP.

**v0.1.0 shipped 2026-05-16.** 4 phases, 10 plans, 68 commits, 4 days. 7,120 lines Python (source + tests). Core loop, UI, distribution all validated.

**v0.2.0 shipped 2026-05-18.** 6 phases (05–09.1), 12 plans, 73 commits, 5 days. 32 files changed, 5,814 insertions. Backend instrumentation (timing, tokens, thoughts, screenshots, training data) complete. Visual rendering of several UI features deferred to v0.3.0 visual refactor.

**Stack confirmed:** browser-use 0.12.6 + cdp-use, FastAPI + HTMX + SSE, PyInstaller for .app, LiteLLM >=1.83.0 hard-pinned. asyncio.Queue as agent-to-SSE bridge is the core architecture.

**Known technical debt entering v0.3.0:**
- CR-01: `step_start` timer in runner.py fires before pre_flight_check — inflates first-step duration
- CR-01/CR-02 from Phase 6 REVIEW: history variable shadow + keys()[0] in log_step
- Visual rendering gaps: `.timestamp` span not visually confirmed; token/cost ticker, action badges, thought blocks, run history expansion may have display issues
- test_events_phase8.py: 3 pre-existing failures (test_jsonl_enriched_fields_anthropic, test_provider_gate_openai_populates_fields, test_thoughts_accumulator_key_alignment)

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Local-first (no cloud deployment) | Datacenter IPs blocked by target sites; residential IP is functionally required | ✓ Good — confirmed during Phase 4 UAT planning |
| BYOM via LiteLLM + ChatOllama | Single abstraction for API providers; ChatOllama direct for local models | ✓ Good — 31 unit tests green, all 3 providers wired |
| browser-use as loop engine | Avoid building agentic loop from scratch; MIT, Python-native, active development | ✓ Good — Stagehand confirmed TypeScript-only; raw Playwright is months of work |
| General-purpose loop as v1 (no presets) | LLM vision handles arbitrary domains — per-domain scrapers are pre-LLM thinking | ✓ Good — loop works; presets are clean v2 additions |
| FastAPI + HTMX + SSE for UI | Zero build step, 30-40KB JS, EventSourceResponse native in FastAPI | ✓ Good — worked cleanly; live screenshot + narration stream both implemented |
| asyncio.Queue as agent-to-SSE bridge | Decouples agent callbacks from HTTP layer; single event loop | ✓ Good — critical architecture that enabled clean pause/stop without threading hacks |
| PyInstaller for .app distribution | Consumer target — zero dependencies, double-click launch | ✓ Good — cdp-use is bundled driver (not Playwright); ad-hoc codesign works |
| macOS first for v1 distribution | Smallest blast radius for validating PyInstaller + codesign + CI pipeline | ✓ Good — Windows CI scaffold exists for v0.3.0 |
| litellm>=1.83.0 hard pin | Supply chain backdoor in 1.82.7/1.82.8 | ✓ Good — neutralized from day 1 |
| TDD for v0.2.0 phases | RED test suite per phase ensures Nyquist coverage before implementation | ✓ Good — caught regressions in Phase 5/6 test updates; RED gate discipline held |
| Defer visual rendering to v0.3.0 | UI backend wiring complete; rendering gaps found in UAT; refactoring UI is cleaner work than patching per-feature | ✓ Pragmatic — backend is solid; v0.3.0 visual refactor is a single focused effort |

## Evolution

This document evolves at phase transitions and milestone boundaries.

**After each phase transition** (via `/gsd-transition`):
1. Requirements invalidated? → Move to Out of Scope with reason
2. Requirements validated? → Move to Validated with phase reference
3. New requirements emerged? → Add to Active
4. Decisions to log? → Add to Key Decisions
5. "What This Is" still accurate? → Update if drifted

**After each milestone** (via `/gsd-complete-milestone`):
1. Full review of all sections
2. Core Value check — still the right priority?
3. Audit Out of Scope — reasons still valid?
4. Update Context with current state

## Current Milestone: v0.3.0 Polish & Presets

**Goal:** Make the app portfolio-ready — fix all visible UI gaps, add a full settings panel with Ollama model discovery and prompt library, build deep prompt engineering for the three core task types, audit browser auth posture, and ship Windows .exe packaging.

**Target features:**
- UI theme & layout overhaul (dark green, blue/red/green badges, real-time status spinner, thought blocks below screen)
- Settings panel (Ollama model discovery, API keys, domain exclusion list, prompt library with A/B support)
- Task presets (apartment, job, candidate search) with domain-tuned prompts
- Deep prompt engineering — generic + per-domain system prompts
- Auth & browser isolation audit (WSL Chrome credential posture)
- Windows .exe packaging via PyInstaller + GitHub Actions
- Portfolio presentation (README, screenshots/GIF, download story)

---
*Last updated: 2026-05-18 — Phase 12 complete — prompt library shipped (PROMPT-01..07)*

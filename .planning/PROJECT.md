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
- ✓ Per-step latency timing + token counting + cost estimation (PERF-01, PERF-02, PERF-04) — Phase 5
- ✓ ThoughtEvent + ActionDetailEvent SSE events via register_new_step_callback (TRANS-01, TRANS-02, TRANS-03) — Phase 6

## Current Milestone: v0.2.0 Foundations

**Goal:** Harden the core loop — instrument performance, surface model transparency, fix screenshot lag, and build the training data pipeline before expanding features.

**Target features:**
- Per-step latency instrumentation + token counting + cost estimation
- Surface LLM thought text and richer action labels in the UI
- Near real-time screenshot streaming (background capture loop + lag fix)
- Training data capture for API providers (Claude/OpenAI) — enriched JSONL with thought, tokens, cost, duration
- LoRA training scaffold: data converter + unsloth training script ready to run
- Frontend polish: action type badges, expandable run history with cost/duration

### Active (v0.2.0)

- [x] Per-step latency timing (PERF-01) — Phase 5
- [x] Token counting + cost estimation per run (PERF-02) — Phase 5
- [ ] UI: step timer, token/cost ticker display (PERF-03)
- [x] Surface LLM thought text in narration feed (TRANS-01) — Phase 6
- [x] Richer action labels: target, value summary, result indicator (TRANS-02) — Phase 6
- [x] Step counter + current goal display (TRANS-03) — Phase 6
- [ ] Background screenshot capture loop (~500ms during action) (SCR-01)
- [ ] Fix screenshot queue backpressure / delivery lag (SCR-02)
- [ ] Enriched JSONL: step_duration_ms, tokens_used, cost_usd, model_thought, provider, model_name (TRAIN-01)
- [ ] API-provider-only capture mode (Claude/OpenAI; skip Ollama) (TRAIN-02)
- [ ] LoRA scaffold: JSONL → training format converter + unsloth training script (TRAIN-03)
- [ ] Narration feed: action type color badges + result indicators (UI-01)
- [ ] Run history: expandable detail (step count, cost, duration) (UI-02)

### Deferred (post-v0.2.0)

- [ ] Windows .exe distribution — GitHub Actions scaffold exists; macOS is the validated path
- [ ] Full Apple notarization (vs ad-hoc codesign) — required for Gatekeeper auto-pass on all Macs
- [ ] Manual smoke test verification — requires human with Chrome + Ollama to verify 5 live scenarios
- [ ] Structured task presets: apartment, job, lead search
- [ ] Authenticated sessions: saved credential sets, session cookie persistence
- [ ] Excel/CSV export of structured run results
- [ ] LoRA training run + evaluation (v0.3.0 — needs 1,000+ quality steps and benchmark suite)

### Out of Scope

- Cloud deployment — datacenter IPs get blocked by apartment/job sites; residential IP is a functional requirement, not just a privacy preference
- Electron wrapper — adds complexity; localhost UI in the system browser is sufficient
- Headless browser — the app uses the user's real Chrome (headed), which avoids bot detection and is the better UX; headless mode not needed
- Authenticated sessions (login, saved credentials) in v1 — apartment search is unauthenticated; credential management is a dedicated v2 feature requiring secure storage design
- Using the user's existing browser — too risky; could corrupt active sessions; agent runs its own isolated Chromium instance
- CAPTCHA solving — not a v1 concern; log and surface to user when encountered
- Multi-user or shared sessions — local single-user tool
- Per-domain scrapers / regex selectors — obsolete; LLM vision handles arbitrary domains; building per-domain logic is regressing to pre-LLM tooling
- Structured task presets in v1 — apartment/job/lead presets are v2, layered on top of the proven general loop
- Fast path (httpx) in v1 — v2 performance optimization once the general agent loop is solid
- Training data pipeline in v1 — session (screenshot, action) pairs are a stretch goal; log them but no LoRA tooling yet
- Voice dictation in v1 — nice-to-have for search input, deferred to v2

## Context

**Prior art — Selenium leads finder:** Built by the developer, broke on JS-heavy pages, dynamic content, CAPTCHAs, and brittle CSS selectors. Motivation for the current approach: vision-driven LLM navigation has no selectors to break, and handles dynamic pages by seeing them as a human does.

**Prior art — Podium:** Developer's BYOK webapp LLM assistant with agentic loops. Architecture reference for the BYOM pattern and provider abstraction.

**Prior art — Apartment finder webapp:** Existing separate repo with live demo. Scraper logic (Craigslist, Zumper via httpx) will be ported as the fast-path for non-JS sites in the apartment preset. The browser agent handles JS-rendered pages where httpx falls short.

**Hardware reality:** Apple Silicon Macs (M1/M2/M3/M4, 16GB+) are tier-1 for local Ollama inference (Metal GPU acceleration, unified memory). NVIDIA RTX 3060 12GB+ on Windows is also excellent. Intel/AMD integrated users should use API providers (Anthropic/OpenAI/Gemini) — the BYOM architecture is the escape hatch for weaker hardware.

**Why local-first:** Residential IP avoids datacenter IP blocks on apartment/job/lead sites. Cloud deployment was evaluated and abandoned for this reason. The browser runs on the user's machine from their IP.

**Research direction:** Validate browser-use as the loop engine (vs Stagehand, vs raw Playwright + custom loop). Confirm LiteLLM covers Ollama + vision models. Identify the right localhost UI pattern for live streaming (research agents to decide between FastAPI+HTMX+SSE vs FastAPI+React/Vite). Flag pitfalls with visible-browser agentic loops at consumer scale.

## Constraints

- **Tech stack**: Python — browser-use, LiteLLM, Playwright are all Python; no reason to deviate
- **Distribution**: Bundled native app — `.app` (Mac) and `.exe` (Windows) via PyInstaller or Briefcase. Double-click to launch, zero dependencies for end users. Built and published via GitHub Actions → GitHub Releases. Developer workflow uses `uv`.
- **Browser**: User's installed Google Chrome via `playwright.chromium.launch(channel="chrome")`. No Chromium download bundled. Headed (visible), residential IP, real browser fingerprint — not flagged as bot. Fallback: friendly prompt to install Chrome if not found.
- **Performance**: Minimize overhead — running Playwright + an LLM is already CPU/RAM intensive; UI must be lightweight
- **Security**: No cloud component; user's API keys stay local; no data leaves the machine except LLM API calls
- **Scope**: v1 is the general-purpose loop — prove it works on any site before building structured presets

## Context

**v0.1.0 shipped 2026-05-16.** 4 phases, 10 plans, 68 commits, 4 days. 7,120 lines Python (source + tests). 35/35 v1 requirements complete.

**Stack confirmed:** browser-use 0.12.6 + cdp-use (replaces Playwright in distribution), FastAPI + HTMX + SSE, PyInstaller for .app. LiteLLM >=1.83.0 hard-pinned (supply chain backdoor neutralized).

**Validated learnings:**
- browser-use is the right loop engine — Stagehand is TypeScript-only; raw Playwright would be months of custom loop work
- asyncio.Queue as SSE bridge is sound — decouples agent from HTTP layer cleanly
- PyInstaller .app works — cdp-use (not Playwright) is the bundled browser driver; Playwright cannot bundle cleanly
- Ad-hoc codesign is sufficient for v1 distribution; Apple notarization is v2

**Next milestone focus:** Windows distribution, full notarization, manual smoke test sign-off, and first structured preset (apartment search).

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
| macOS first for v1 distribution | Smallest blast radius for validating PyInstaller + codesign + CI pipeline | ✓ Good — Windows CI scaffold exists for v0.2.0 |
| litellm>=1.83.0 hard pin | Supply chain backdoor in 1.82.7/1.82.8 | ✓ Good — neutralized from day 1 |

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

---
*Last updated: 2026-05-17 — Phase 6 complete: ThoughtEvent + ActionDetailEvent wired, 133 tests GREEN*

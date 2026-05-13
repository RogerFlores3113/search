# local-browser-agent

## What This Is

A consumer-grade local AI browser agent — download, double-click, done. The app drives the user's own Chrome from their machine and residential IP, the LLM has full browser control (click, type, scroll, navigate), and every step streams live to a localhost web UI. User types any natural language task; the agent completes it on any site. No Python, no terminal, no cloud required.

## Core Value

User types any natural language task, the agent opens Chrome and completes it — a general-purpose agentic loop that works on arbitrary sites before structured presets are layered on top.

## Requirements

### Validated

(None yet — ship to validate)

### Active

- [ ] General-purpose agentic loop: screenshot → LLM decision → browser action → repeat (any site, any task)
- [ ] LLM has full browser control: click, type, scroll, navigate — no per-domain logic
- [ ] browser-use as the loop engine (Python-native, MIT, validated over raw Playwright)
- [ ] BYOM: Ollama (local, Qwen2.5-VL:7b recommended), Anthropic (Claude), OpenAI (GPT-4o)
- [ ] Guardrails: global domain blocklist + action system-prompt instructions (no payment CTAs, no credential submission outside user-directed sites)
- [ ] Localhost web UI: prompt box, live screenshot stream, narration feed, state/progress, pause/stop
- [ ] Run history: task, status, timestamp saved locally; recent runs viewable
- [ ] Mac .app distribution: double-click launch, no dependencies, drives user's Chrome
- [ ] Safety disclaimer on first launch

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

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Local-first (no cloud deployment) | Datacenter IPs blocked by target sites; residential IP is functionally required | — Pending |
| BYOM via LiteLLM | Single abstraction for Ollama + all major API providers; user brings their own key | — Pending |
| browser-use as loop engine (to validate) | Avoid building agentic loop from scratch; research to confirm it's the right foundation | — Pending |
| General-purpose loop as v1 (no presets) | LLM vision handles arbitrary domains — per-domain scrapers are pre-LLM thinking; prove the loop first | — Pending |
| Localhost UI (no Electron) | Simpler distribution; system browser is sufficient; lower resource overhead | — Pending |
| Native bundled app (.app / .exe) | Consumer app target — zero dependencies, double-click launch; uses user's Chrome via `channel="chrome"` | — Pending |

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
*Last updated: 2026-05-13 after initialization*

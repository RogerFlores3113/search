# local-browser-agent

## What This Is

A local-first agentic browser automation framework with a bring-your-own-model (BYOM) architecture. The agent runs entirely on the user's machine — a visible Playwright browser window captures screenshots, an LLM decides the next action (click/type/scroll), and results are streamed live to a localhost web UI. Users bring their own model (Ollama, Anthropic, OpenAI, Gemini) or point at a local Ollama instance. Designed for tech-adjacent users who want a real UI, not a config file.

## Core Value

A working apartment finder preset that completes a real search end-to-end from a residential IP — proving the local agentic loop works before any other preset is built.

## Requirements

### Validated

(None yet — ship to validate)

### Active

- [ ] Core agentic loop: screenshot → LLM decision → browser action → repeat until done
- [ ] browser-use integration as the loop engine (evaluate vs raw Playwright + custom loop)
- [ ] LiteLLM provider abstraction: Ollama (local), Anthropic, OpenAI, Gemini
- [ ] Apartment finder preset (port from existing webapp): goal, allowed domains, search constraints, output schema
- [ ] Fast path for non-JS sites (Craigslist, Zumper via httpx) alongside full agentic loop
- [ ] Domain allowlist enforcement per preset (guardrails)
- [ ] Action blocklist: no bank sites, no email composition, no out-of-scope form submissions
- [ ] Localhost web UI with live status updates, spinners, and streaming result tables
- [ ] Output to SQLite and/or Excel (.xlsx) files
- [ ] Cross-platform launch script: opens localhost UI in user's browser (Windows/Mac/Linux)
- [ ] User-facing safety disclaimer on launch
- [ ] Preset viewer/editor: users can inspect and tweak preset config

### Out of Scope

- Cloud deployment — datacenter IPs get blocked by apartment/job sites; residential IP is a functional requirement, not just a privacy preference
- Electron wrapper — adds complexity; localhost UI in the system browser is sufficient
- CAPTCHA solving — not a v1 concern; log and surface to user when encountered
- Multi-user or shared sessions — local single-user tool
- Custom preset builder (GUI) in v1 — presets are editable config files; GUI builder is v2
- Training data pipeline in v1 — session (screenshot, action) pairs are a stretch goal; log them but no LoRA tooling yet

## Context

**Prior art — Selenium leads finder:** Built by the developer, broke on JS-heavy pages, dynamic content, CAPTCHAs, and brittle CSS selectors. Motivation for the current approach: vision-driven LLM navigation has no selectors to break, and handles dynamic pages by seeing them as a human does.

**Prior art — Podium:** Developer's BYOK webapp LLM assistant with agentic loops. Architecture reference for the BYOM pattern and provider abstraction.

**Prior art — Apartment finder webapp:** Existing separate repo with live demo. Scraper logic (Craigslist, Zumper via httpx) will be ported as the fast-path for non-JS sites in the apartment preset. The browser agent handles JS-rendered pages where httpx falls short.

**Hardware reality:** Apple Silicon Macs (M1/M2/M3/M4, 16GB+) are tier-1 for local Ollama inference (Metal GPU acceleration, unified memory). NVIDIA RTX 3060 12GB+ on Windows is also excellent. Intel/AMD integrated users should use API providers (Anthropic/OpenAI/Gemini) — the BYOM architecture is the escape hatch for weaker hardware.

**Why local-first:** Residential IP avoids datacenter IP blocks on apartment/job/lead sites. Cloud deployment was evaluated and abandoned for this reason. The browser runs on the user's machine from their IP.

**Research direction:** Validate browser-use as the loop engine (vs Stagehand, vs raw Playwright + custom loop). Confirm LiteLLM covers Ollama + vision models. Identify the right localhost UI pattern for live streaming (research agents to decide between FastAPI+HTMX+SSE vs FastAPI+React/Vite). Flag pitfalls with visible-browser agentic loops at consumer scale.

## Constraints

- **Tech stack**: Python — browser-use, LiteLLM, Playwright are all Python; no reason to deviate
- **Distribution**: Cross-platform launch script, no Electron, no cloud required
- **Performance**: Minimize overhead — running Playwright + an LLM is already CPU/RAM intensive; UI must be lightweight
- **Security**: No cloud component; user's API keys stay local; no data leaves the machine except LLM API calls
- **Scope**: v1 is apartment preset only — prove the loop before adding presets

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Local-first (no cloud deployment) | Datacenter IPs blocked by target sites; residential IP is functionally required | — Pending |
| BYOM via LiteLLM | Single abstraction for Ollama + all major API providers; user brings their own key | — Pending |
| browser-use as loop engine (to validate) | Avoid building agentic loop from scratch; research to confirm it's the right foundation | — Pending |
| Apartment preset as v1 anchor | Existing scraper logic to port; clearest success criteria; single preset proves framework | — Pending |
| Fast path (httpx) + full agentic path | Non-JS sites don't need a full browser loop; hybrid is more efficient and reliable | — Pending |
| Localhost UI (no Electron) | Simpler distribution; system browser is sufficient; lower resource overhead | — Pending |

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

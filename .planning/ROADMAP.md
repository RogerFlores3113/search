# Roadmap: local-browser-agent

## Overview

Four phases from clean scaffold to distributable Mac app. Phase 1 proves the agentic loop works from the CLI with one model. Phase 2 adds all model providers and hardens guardrails. Phase 3 wraps everything in a full localhost web UI — prompt box, live screenshot stream, narration feed, pause/stop. Phase 4 packages it as a double-click Mac .app with CI/CD.

The apartment search is a v1 *test case* to validate the loop, not a hardcoded preset. Structured presets (apartment, job, lead search) come in v2 once the general loop is proven solid.

## Phases

- [ ] **Phase 1: Scaffold + Core Loop PoC** — uv/pyproject setup, browser-use + Ollama wired, agent navigates a real URL from CLI
- [ ] **Phase 2: Multi-Provider + Guardrails** — Anthropic and OpenAI added, domain blocklist and action guardrails enforced
- [ ] **Phase 3: Full Web UI** — Prompt box, live screenshot stream, narration feed, state/progress, pause/stop, run history
- [ ] **Phase 4: Distribution** — Mac .app bundle, Chrome detection, auto-open browser, safety disclaimer, GitHub Actions CI

---

## Phase Details

### Phase 1: Scaffold + Core Loop PoC
**Goal:** A developer can type a natural language task at the CLI and watch browser-use drive Chrome to complete it — proving the asyncio architecture is sound and critical pitfalls are neutralized before any UI work begins.
**Mode:** mvp
**Depends on:** Nothing (first phase)
**Requirements:** LOOP-02, LOOP-03, LOOP-04, LOOP-05, LOOP-06, MODEL-01, MODEL-04

**Success Criteria** (what must be TRUE):
1. `uv run python -m agent "go to Wikipedia and find the page for the Eiffel Tower"` completes without error; pyproject.toml has `litellm>=1.83.0` pinned
2. browser-use agent drives the user's real Chrome (headed, `channel="chrome"`), navigates to a real URL, and logs each step action to stdout in plain language
3. Agent terminates automatically when `max_steps` is reached (default: 25) without hanging the process or leaving orphan Chrome windows
4. Agent terminates automatically on session timeout (default: 10 min) via `asyncio.wait_for`
5. Model validation runs before the session starts; actionable error message printed if Ollama is not running or model not pulled (e.g., "Run: ollama pull qwen2.5vl:7b")

**Critical pitfalls to resolve in this phase:**
- Pin `litellm>=1.83.0` as step zero (supply chain backdoor in 1.82.7/1.82.8)
- Validate `async_playwright()` works inside FastAPI's asyncio event loop on Day 1 — hard crash otherwise
- Never use `Browser(keep_alive=True)` — hangs event loop (browser-use issue #3791)
- Confirm Chrome v136 CDP workaround — launch Chrome with `--user-data-dir` flag or resolve via `channel="chrome"` behavior
- Wrap `agent.run()` in `asyncio.wait_for()` — no default termination without this

**Plans:** 2/3 plans executed

Plans:
**Wave 1**
- [x] 01-01-PLAN.md — Wave 0: uv project scaffold, layered agent/ package stubs, pytest test stubs with litellm>=1.83.0 pin
- [x] 01-02-PLAN.md — Wave 1: implement pre_flight_check + log_step + run_agent; wire FastAPI lifespan + uvicorn entrypoint; turn xfails green

**Wave 2** *(blocked on Wave 1 completion)*
- [ ] 01-03-PLAN.md — Wave 2: automated end-to-end TestClient integration; manual smoke test on live Chrome + Ollama

---

### Phase 2: Multi-Provider + Guardrails
**Goal:** All three model providers are selectable and work correctly; the domain blocklist and action guardrails prevent the agent from doing anything outside the user's intent, regardless of what the LLM tries.
**Mode:** mvp
**Depends on:** Phase 1
**Requirements:** MODEL-02, MODEL-03, GUARD-01, GUARD-02, GUARD-03, GUARD-04

**Success Criteria** (what must be TRUE):
1. Selecting Anthropic (Claude) with a valid API key runs a navigation task successfully; key is stored in local config, never logged or transmitted elsewhere
2. Selecting OpenAI (GPT-4o) with a valid API key runs a navigation task successfully; same key handling
3. Navigating to a domain on the blocklist (e.g., a banking domain) is intercepted at the Playwright `page.route()` level — the page never loads; a blocked-domain event is logged to stdout
4. A simulated "Buy Now" / "Purchase" CTA click is blocked by the system prompt guardrail — verified by injecting a test page with such a button
5. If a CAPTCHA is detected mid-run, the agent pauses and prints a clear notification; the run does not silently continue or silently fail

**Plans:** 2 plans

Plans:
**Wave 1**
- [x] 02-01-PLAN.md — Multi-provider LLM (Anthropic + OpenAI): SecretStr config, build_llm factory, pre_flight_check branches

**Wave 2** *(blocked on Wave 1 completion)*
- [x] 02-02-PLAN.md — Guardrails: BrowserProfile prohibited_domains, extend_system_message safety prompt, log_step CAPTCHA detection + agent.pause()


---

### Phase 3: Full Web UI
**Goal:** The agent runs entirely from a localhost web UI — user types a task, watches Chrome work in real time via a live screenshot stream and narration feed, can pause or stop the run, and sees a plain-language summary when done.
**Mode:** mvp
**Depends on:** Phase 2
**Requirements:** LOOP-01, LOOP-07, LOOP-08, LOOP-09, LOOP-10, UI-01, UI-02, UI-03, UI-04, UI-05, UI-06, UI-07, UI-08, UI-09, RUN-01, RUN-02, RUN-03

**Success Criteria** (what must be TRUE):
1. User types "find the Wikipedia page for the Eiffel Tower" in the prompt box and presses Enter — the agent starts without any other action
2. The current browser viewport screenshot updates in the UI within 1 second of each agent step — user sees what the agent sees as it happens
3. A plain-language narration event appears in the feed within 1 second of each step ("Navigating to Wikipedia...", "Typing in search box...", "Found article — reading...")
4. The UI shows one of five states at all times (idle / running / paused / complete / error) — state is never stuck or inconsistent
5. Pause halts the agent mid-step; Stop terminates the agent and closes Chrome with no orphan processes — both verified by manual test
6. Completed run shows a plain-language summary of what was accomplished; failed run shows a human-readable error, not a stack trace
7. Each completed run is saved locally (task prompt, narration log, summary, status, timestamp); recent runs list shows at minimum the last 10 runs
8. Every agent step writes a training record to `training/runs.jsonl`: screenshot (base64), action type, action target, action value, narration, and step success flag — file exists and grows with each run

**Architecture contract (must hold to prevent Phase 3 becoming a rewrite):**
- Single asyncio event loop (uvicorn owns it); browser-use agent runs as `asyncio.create_task()`
- `asyncio.Queue` per run as the sole bridge between agent callbacks and the SSE endpoint
- SSE endpoint is an async generator that `await queue.get()` loops until `DoneEvent`
- Screenshots from browser-use's `on_step_end` callback are base64-encoded and put on the queue as `ScreenshotEvent`
- No `BackgroundTasks` for the agent — it blocks the event loop

**UI hint:** yes

**Plans:** 3 plans

Plans:
**Wave 1**
- [x] 03-01-PLAN.md — Skeleton vertical slice: aiosqlite dep + events.py + db.py + queue-bridged run_agent + SSE endpoint + HTMX/Alpine index.html (LOOP-01, LOOP-09, UI-01, UI-03, UI-04)

**Wave 2** *(blocked on Wave 1 completion)*
- [x] 03-02-PLAN.md — Visual fidelity slice: ScreenshotEvent + ProgressEvent + SummaryEvent emission, Alpine handlers, full UI-SPEC CSS, inline error/summary boxes (UI-02, UI-05, UI-08, UI-09, LOOP-10)

**Wave 3** *(blocked on Wave 2 completion)*
- [x] 03-03-PLAN.md — Controls + history slice: /pause /stop /runs endpoints, runner→insert_run, Recent Runs panel + Pause/Stop buttons (LOOP-07, LOOP-08, UI-06, UI-07, RUN-01, RUN-02, RUN-03)

---

### Phase 4: Distribution
**Goal:** A non-technical Mac user downloads the app from GitHub Releases, double-clicks it, and the app opens in their browser within seconds — no Python, no terminal, no setup of any kind.
**Mode:** mvp
**Depends on:** Phase 3
**Requirements:** DIST-01, DIST-02, DIST-03, DIST-04, DIST-05

**Success Criteria** (what must be TRUE):
1. A `.app` bundle on Mac launches by double-clicking — verified on a machine with no Python, no uv, no Homebrew installed
2. App detects the user's installed Chrome via `channel="chrome"` automatically; if Chrome is not found, the app shows: "Google Chrome is required. [Download Chrome]" with a link
3. The app opens the user's default browser to `localhost:8080` within 3 seconds of double-clicking
4. First-time users see a one-time safety disclaimer before the prompt box is accessible — explains what the agent does, what it won't do, and that it acts on their behalf
5. Pushing a version tag (e.g., `v0.1.0`) to the main branch triggers GitHub Actions, which builds the `.app`, code-signs it (or notarizes with ad-hoc signing for v1), and uploads it to GitHub Releases — verified end-to-end

**Plans:** 2 plans

Plans:
**Wave 1**
- [ ] 04-01-PLAN.md — Vertical slice: frozen-aware paths + Chrome detection + auto-open + disclaimer modal + PyInstaller spec (DIST-01, DIST-02, DIST-03, DIST-04)

**Wave 2** *(blocked on Wave 1 completion)*
- [ ] 04-02-PLAN.md — GitHub Actions release pipeline + README Gatekeeper instructions + clean-Mac UAT script (DIST-05, DIST-01)

---

## Progress

**Execution Order:** 1 → 2 → 3 → 4

| Phase | Status | Completed |
|-------|--------|-----------|
| 1. Scaffold + Core Loop PoC | Not started | — |
| 2. Multi-Provider + Guardrails | Not started | — |
| 3. Full Web UI | Not started | — |
| 4. Distribution | Not started | — |

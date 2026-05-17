# Retrospective: local-browser-agent

---

## Milestone: v0.1.0 — MVP

**Shipped:** 2026-05-16
**Phases:** 4 | **Plans:** 10 | **Commits:** 68

### What Was Built

- Agentic loop scaffold: uv/pyproject + litellm>=1.83.0 supply-chain pin + Ollama/qwen2.5-VL integration
- Full loop engine: browser-use + Chrome + asyncio.wait_for + JSONL training logger (all 5 critical pitfalls neutralized)
- Multi-provider BYOM: Ollama, Anthropic, OpenAI via `build_llm()` factory with SecretStr key storage
- Safety guardrails: CDP domain blocking (SecurityWatchdog) + GUARDRAIL_PROMPT system message + CAPTCHA detection + pause
- FastAPI + HTMX + SSE web UI: live screenshot stream, narration feed, state machine, pause/stop controls, run history panel
- Mac .app distribution: PyInstaller + frozen path redirection + Chrome detection + disclaimer modal + GitHub Actions release pipeline

### What Worked

- **Vertical slice approach per phase** — each plan delivered a working E2E slice before adding layers. Phase 3 went skeleton → visual fidelity → controls rather than doing all UI at once.
- **Critical pitfall documentation in ROADMAP** — Phase 1 listed 5 specific pitfalls to neutralize (litellm pin, asyncio.wait_for, keep_alive=False, Chrome CDP, async_playwright). All 5 were resolved cleanly in 01-02.
- **asyncio.Queue as the SSE bridge** — this was the right call. Decoupling agent callbacks from the HTTP layer via a queue made pause/stop trivial to implement in Phase 3.
- **cdp-use discovery in Phase 4** — browser-use 0.12.6 uses cdp-use instead of Playwright for browser control in distribution, which meant PyInstaller doesn't need to bundle Playwright. Caught during research.
- **TDD on the agentic loop** — mocking Agent.run/BrowserSession at module level produced real structural proofs (log_step executes, JSONL writes, browser.kill awaited) without Chrome or Ollama.

### What Was Inefficient

- **REQUIREMENTS.md traceability table not updated after Phase 1** — by Phase 4 the table was 26 requirements behind. Required manual fix at milestone close. Should update traceability after each phase.
- **ROADMAP progress table not updated during execution** — the bottom progress table still showed "Not started" at milestone close. Progress was tracked in STATE.md instead.
- **Manual smoke test (01-03 Task 2)** — requires human with Chrome + Ollama; was noted as pending checkpoint but never scheduled. Will need explicit calendar time in v0.2.0 planning.

### Patterns Established

- `build_llm(cfg)` factory pattern: single function returns the right LLM object (ChatOllama or ChatLiteLLM) based on config — clean BYOM abstraction
- `asyncio.Queue` per run as agent-to-SSE bridge — put events on queue in callbacks, drain in SSE generator
- `sys.frozen` check + platformdirs for path redirection — distinguishes bundled .app from dev environment cleanly
- `BrowserSession(keep_alive=False)` — always; `keep_alive=True` hangs the event loop

### Key Lessons

1. **litellm pin is non-negotiable** — the supply chain backdoor in 1.82.7/1.82.8 was a real event. `>=1.83.0` is the floor forever.
2. **cdp-use, not Playwright, is the distribution browser driver** — browser-use 0.12.6 switched from Playwright to cdp-use internally. PyInstaller specs should not `collect_data_files("playwright")`.
3. **asyncio is the right foundation** — uvicorn owns the event loop; browser-use runs as create_task; SSE is an async generator. No threads, no BackgroundTasks for the agent.
4. **Vertical slices prevent integration surprise** — building skeleton → then visual fidelity → then controls meant each plan shipped something runnable, not partially complete layers.

### Cost Observations

- Model mix: primarily Sonnet 4.6 throughout
- Sessions: ~8-10 sessions across 4 days
- Notable: Phase 3 required several fix commits after code review (SSE double-encoding, form data handling, Alpine scope issues) — code review pass before commit would have saved 6 fix commits

---

## Cross-Milestone Trends

| Milestone | Days | Phases | Plans | Fix Commits | Pattern |
|-----------|------|--------|-------|-------------|---------|
| v0.1.0 | 4 | 4 | 10 | ~6 | Vertical slices + TDD worked well; traceability debt accumulated |

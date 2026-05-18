# Milestones: local-browser-agent

## v0.2.0 Foundations (Shipped: 2026-05-18)

**Phases completed:** 6 phases, 12 plans, 16 tasks

**Key accomplishments:**

- One-liner:
- One-liner:
- One-liner:
- One-liner:
- Patch targets (all 12 tests use this stack):
- Background _screenshot_loop delivering continuous JPEG frames via SSE; _log_step ScreenshotEvent emission removed; all 12 Phase 7 RED tests now GREEN
- [Rule 1 - Bug] CR-01 and CR-02 fixes were already present in agent/runner.py
- `agent/runner.py`
- Question:
- One-liner:
- One-liner:

---

---

## v0.1.0 MVP — Shipped 2026-05-16

**Phases:** 1–4 | **Plans:** 10 | **Commits:** 68 | **Timeline:** 4 days (2026-05-13 → 2026-05-16)
**Python:** 7,120 lines (source + tests) | **Files changed:** 59 | **Insertions:** 12,973

**Delivered:** General-purpose local AI browser agent — browser-use + BYOM (Ollama/Anthropic/OpenAI) + FastAPI/HTMX/SSE web UI + Mac .app distribution via GitHub Actions.

### Key Accomplishments

1. Proved the general-purpose agentic loop: browser-use + Ollama (qwen2.5-VL) + Chrome — screenshot → LLM decision → browser action → repeat — on any site, any task
2. Multi-provider BYOM via `build_llm()` factory: Ollama (local), Anthropic (Claude), OpenAI (GPT-4o) — all wired with SecretStr API key storage, 31 green unit tests
3. Safety guardrails: CDP-level domain blocking (BrowserProfile.prohibited_domains + SecurityWatchdog), action system-prompt (no payment CTAs, no credential submission), CAPTCHA detection with agent pause
4. Full localhost web UI: FastAPI + HTMX + SSE — live screenshot stream, narration feed, state machine (idle/running/paused/complete/error), progress counter, pause/stop controls, run history panel
5. Run history + training JSONL: every step logged with `{screenshot_b64, action_type, action_target, action_value, narration, step_success}` — foundation for future LoRA fine-tuning
6. Double-click Mac .app distribution: PyInstaller bundle with frozen path redirection (platformdirs), Chrome detection + no-chrome fallback, browser auto-open, one-time disclaimer modal; GitHub Actions tag-triggered release pipeline with ad-hoc codesign

### Requirements

- v1 requirements: **35/35 complete**
- Known gaps at close: none (traceability table was stale during execution, corrected at archive)

### Archived

- `.planning/milestones/v0.1.0-ROADMAP.md`
- `.planning/milestones/v0.1.0-REQUIREMENTS.md`

---

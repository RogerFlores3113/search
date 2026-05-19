# Project Research Summary

**Project:** local-browser-agent
**Domain:** Consumer-grade local AI browser agent — settings panel, prompt library, task presets, Windows packaging (v0.3.0 Polish & Presets)
**Researched:** 2026-05-18
**Confidence:** HIGH

## Executive Summary

v0.3.0 is an infrastructure and UX polish milestone layered on top of a working agentic loop. The core browser-use/FastAPI/HTMX/SSE foundation from v0.2.0 is unchanged; this milestone adds the configuration surface users need to actually own and tune the tool: persistent settings, named system prompt management, task presets, and Windows distribution. The architecture is already correct — v0.3.0 is widening it, not restructuring it.

The recommended build order is dependency-driven and de-risks in layers: DB schema first (unblocks everything), backend routes second, runner wiring third, UI fourth, Windows packaging last. The one new production dependency is `ollama>=0.6.2`; model discovery via `/api/tags` is already 90% implemented in `pre_flight_check()` and needs only a dedicated route. API keys must go into a `settings.json` under `user_data_dir` (via platformdirs), not SQLite and not `keyring` — `keyring` fails in PyInstaller bundles without non-trivial hidden-import surgery, and the single-user local threat model does not require OS keychain encryption. Domain exclusion safety defaults must be enforced in a hardcoded Python frozenset, not just in the UI or the database.

Three security decisions must be locked in before any code ships: (1) GUARDRAIL_PROMPT trails the user system prompt as a suffix (recency weight), and is a code constant — not editable from the UI; (2) domain exclusion safety defaults live in `config.py` as `SAFETY_DEFAULTS: frozenset[str]` and cannot be removed by any API call or SQLite edit; (3) CVE-2025-47241 (domain blocklist URL auth bypass, CVSS 9.3) must be verified as patched in browser-use 0.12.6 before shipping the editable exclusion list. Windows packaging requires `multiprocessing.freeze_support()` first in `__main__.py`, `console=False` with an explicit stdout redirect to a log file, and onedir (not onefile) to avoid Windows Defender false positives.

---

## Key Findings

### Recommended Stack

The v0.2.0 stack is the right foundation and requires no changes. The only addition is `ollama>=0.6.2` as a production dependency for typed model discovery (`ollama.list()` returns `ListResponse` with name, size, family, param_size). However, ARCHITECTURE.md confirms `pre_flight_check()` already calls `GET /api/tags` via `httpx` — so the actual choice is: add the `ollama` library for typed ergonomics, or reuse the existing `httpx` call for zero new dependencies. Either is valid; the httpx path avoids adding a dependency whose transitive relationship to browser-use is indirect.

API key storage research produced a clear conflict between STACK.md and PITFALLS.md that resolves cleanly: PITFALLS.md recommends `keyring` as primary storage, but STACK.md documents that `keyring` raises `RuntimeError: No recommended backend` in PyInstaller bundles without explicit hidden imports — and the `settings.json` approach (via platformdirs) is the correct path for this project. **Decision: store API keys in `settings.json` under `user_data_dir`. Do not add `keyring`.**

**Core technologies (v0.3.0 additions only):**
- `ollama>=0.6.2`: Ollama model discovery — OR reuse existing httpx call in `pre_flight_check()` (no new dep)
- `platformdirs>=4.9.6`: Already in pyproject.toml; `user_config_path()` for settings.json persistence
- `PyInstaller==6.20.0`: Already in dev deps; Windows spec file extends Mac spec with documented differences
- HTMX 2.x + Alpine.js 3.x: Already in stack; drawer overlay pattern for settings panel, no new JS libraries

**What NOT to add:** `keyring`, `python-dotenv`, `keyrings.alt`, UPX compression, Electron, separate settings SQLite database.

### Expected Features

**Must have (table stakes) — ship in v0.3.0:**
- Persistent API key storage (settings.json, masked input, show/hide toggle)
- Ollama model auto-discovery + provider/model selector
- Domain exclusion list with non-editable safety defaults + user-extensible additions
- Settings persistence across launches
- Active system prompt indicator near task input
- Prompt library seed data (4 curated prompts on first init — empty library is a UX dead end)

**Should have (competitive differentiators) — ship in v0.3.0:**
- Prompt library with named saves (CRUD: create, name, list, set active, delete)
- 3 task preset buttons (apartment, job, candidate) that pre-fill task input and select a linked system prompt
- 4 deep domain system prompts (generic, apartment search, job search, candidate/lead search) — full content drafted and ready in FEATURES.md
- A/B testing linkage: store `prompt_id` on each run record in `run_history` for post-hoc comparison

**Defer to v1.x:**
- Prompt version history / diff view
- A/B testing comparison UI
- Export/import prompt library as JSON

**Defer to v2+:**
- Authenticated sessions (saved logins via OS keychain)
- Preset marketplace / community prompt sharing

**Anti-features to explicitly reject:** pickle for settings serialization (CVE-level), API keys in `.env` committed to git, mid-run prompt switching, cloud sync for prompt library.

### Architecture Approach

v0.3.0 extends the existing component graph by adding a `settings` table and `prompt_library` table to the existing `history.db` (via additive `CREATE TABLE IF NOT EXISTS` in `init_db()`), a family of new FastAPI routes in `main.py`, and wiring in `runner.py` to merge `SAFETY_DEFAULTS | user_blocked_domains` and fetch the active prompt at task-start. The `asyncio.Queue` event bridge, the `config` singleton pattern, and the `_resource_path()` frozen-path resolver are all preserved unchanged. The settings panel is an HTMX out-of-band swap drawer managed by Alpine.js local state.

**Major components added or modified:**
1. `agent/db.py` — New `settings` and `prompt_library` tables; CRUD helpers
2. `agent/config.py` — `blocked_domains` field replaced by `SAFETY_DEFAULTS: frozenset[str]` module-level constant
3. `agent/runner.py` — Config snapshot at task-start; domain merge before `BrowserProfile()`; active prompt + GUARDRAIL_PROMPT suffix composition before `Agent()`
4. `agent/main.py` — New routes: `/api/ollama-models`, `/api/settings`, `/api/prompts` (CRUD), `/api/blocked-domains` (CRUD)
5. `agent/templates/settings_fragment.html` — New settings drawer fragment
6. `agent/chrome_detect.py` — Windows Chrome path detection
7. `agent/__main__.py` — `multiprocessing.freeze_support()` on `win32` before any other code
8. `local-browser-agent-windows.spec` — New spec file (no BUNDLE step, `console=False`, `upx=False`, `.ico` icon)
9. `.github/workflows/build-windows.yml` — New CI workflow

**Key invariants to preserve:**
- `asyncio.Queue` is the only bridge between agent callbacks and HTTP layer — no threading
- `BrowserProfile.prohibited_domains` set once per `run_agent()` call — no runtime mutation
- `config` singleton mutated (never re-instantiated) in route handlers
- `_resource_path()` pattern required for any new bundled resource

### Critical Pitfalls

1. **API keys in plaintext SQLite or config.json** (V3-1) — Store in `settings.json` under `user_data_dir` via `platformdirs.user_config_path()`. Do not add `keyring` (fails in PyInstaller bundles). Must be designed before the first settings form is built.

2. **CVE-2025-47241: browser-use domain blocklist URL auth bypass** (V3-7, CVSS 9.3) — URL formatted as `https://allowed.com:pass@blocked.com/path` bypasses `prohibited_domains` check in versions <=0.1.44. Verify patch is present in browser-use 0.12.6 (`_is_url_allowed()` must use `urllib.parse.urlparse()` not raw colon-split) before shipping the editable exclusion list.

3. **GUARDRAIL_PROMPT position and editability** (V3-5) — Assemble as `user_prompt + "\n\n" + GUARDRAIL_PROMPT`. Guardrail trails as suffix (higher recency weight). GUARDRAIL_PROMPT is a code constant, never a user-editable field. Prompt library saves behavioral prompts only.

4. **Windows PyInstaller: console=False + asyncio + freeze_support** (V3-3) — `console=False` makes `sys.stdout = None`; uvicorn startup crashes on `sys.stdout.isatty()`. Redirect stdout/stderr to a log file in frozen path before uvicorn starts. `multiprocessing.freeze_support()` must be the first call in `__main__.py`. Use onedir not onefile. Do not use UPX.

5. **Config mutation race during active task** (V3-9) — Snapshot `active_prompt`, `provider`, `model` as local variables at the top of `run_agent()`. Mid-run settings changes take effect on the next task only. Required for A/B prompt attribution integrity in JSONL training records.

6. **Domain exclusion safety defaults editable at data layer** (V3-6) — `SAFETY_DEFAULTS` must be a hardcoded Python frozenset that is always merged regardless of what is in the database. Database rows for defaults are display-only, not enforcement.

---

## Implications for Roadmap

### Phase 1: DB Schema Foundation
**Rationale:** Every other v0.3.0 feature reads from or writes to `settings` and `prompt_library` tables. Critical path dependency — nothing else can be unit-tested until schema and CRUD layer exist.
**Delivers:** `settings` and `prompt_library` tables in `init_db()`; CRUD helpers in `agent/db.py`; `SAFETY_DEFAULTS` frozenset in `config.py`
**Addresses:** Settings persistence (table stakes), prompt library data layer, domain exclusion data layer
**Avoids:** Anti-pattern of building UI before backend exists (V3-6 two-layer domain enforcement must be in design from the start)

### Phase 2: Backend Routes
**Rationale:** Settings panel UI requires working endpoints before HTMX forms can be wired. Route-first allows curl/httpie testing before any HTML is written.
**Delivers:** `/api/ollama-models`, `/api/settings` GET+POST, `/api/prompts` CRUD, `/api/blocked-domains` GET+POST+DELETE
**Addresses:** Ollama model auto-discovery (already 90% done in `pre_flight_check` — extract to route), API key persistence, prompt CRUD
**Avoids:** Ollama model discovery race (V3-2) — endpoint must return gracefully when Ollama is not running

### Phase 3: Runner Wiring
**Rationale:** `run_agent()` must consume the new DB layer before the settings UI is built — otherwise the UI can write to DB but the agent won't see it.
**Delivers:** Config snapshot pattern at task-start; domain merge (`SAFETY_DEFAULTS | user_blocked_domains`) before `BrowserProfile()`; active prompt + GUARDRAIL_PROMPT suffix composition before `Agent()`; `prompt_id` stored on run record
**Avoids:** Config mutation race (V3-9); GUARDRAIL_PROMPT position (V3-5); domain defaults bypass (V3-6)

### Phase 4: Settings UI + Prompt Library + Task Presets
**Rationale:** Pure frontend work unblocked once Phase 2 routes exist. UI theme changes (dark green, badge colors) batch here as CSS-only work.
**Delivers:** Settings drawer (HTMX out-of-band swap, Alpine.js tab panel), API key inputs (masked, show/hide), provider/model selector with Ollama auto-discovery, domain exclusion two-tier list, prompt library CRUD UI, active prompt indicator, 3 preset buttons (apartment/job/candidate), prompt library seeded with 4 curated prompts on first init
**Avoids:** Empty-state problem on first launch (seed 4 prompts); real-time prompt switching anti-feature

### Phase 5: Auth Audit Documentation
**Rationale:** AUTH-01 is a documentation and verification task. Chrome isolation (fresh empty profile) is already correct — this phase confirms it, documents it, and verifies the CVE-2025-47241 patch status.
**Delivers:** Verified `BrowserProfile` always uses isolated `user_data_dir`; SECURITY.md note documenting fresh-profile-only policy; WSL constraint documented; CVE-2025-47241 patch confirmed in 0.12.6
**Avoids:** Chrome credential access misconception (V3-8)

### Phase 6: Windows Packaging
**Rationale:** No blockers from other phases; longest feedback loop (requires Windows runner). Independent and safe to parallelize with Phase 4 if bandwidth allows.
**Delivers:** `chrome_detect.py` Windows paths; `multiprocessing.freeze_support()` in `__main__.py`; `local-browser-agent-windows.spec` (onedir, `console=False`, `upx=False`, `.ico`); `build_scripts/build_windows.bat`; `.github/workflows/build-windows.yml`; stdout/stderr redirect to log file for frozen Windows path
**Avoids:** Windows PyInstaller asyncio+console crashes (V3-3); Windows Defender false positives (onefile, UPX)

### Phase Ordering Rationale

The dependency graph is strict: DB schema → CRUD functions → backend routes → runner wiring → UI. Each layer is a prerequisite for the next. Windows packaging is the only independent track and can run in parallel with Phase 4 once Phase 3 is done. Auth audit is a verification gate before the editable domain exclusion list ships in Phase 4 (CVE-2025-47241 patch status must be confirmed first).

The three security decisions (GUARDRAIL_PROMPT as suffix, SAFETY_DEFAULTS as hardcoded constant, API keys in settings.json not keyring) must be locked in during Phase 1 design — not retrofitted after Phase 4.

### Research Flags

Phases needing `/gsd-research-phase` deeper research during planning:
- **Phase 4 (Settings UI):** The interaction between the settings drawer state and an active running task needs careful design — the Ollama model refresh button must not mutate `config.ollama_model` mid-run
- **Phase 6 (Windows Packaging):** `console=False` + uvicorn + frozen path stdout redirect needs validation on a clean Windows VM; behavior may differ between Python 3.11 and 3.12 on `windows-latest`

Phases with standard, well-documented patterns (skip research-phase):
- **Phase 1 (DB Schema):** Standard aiosqlite `CREATE TABLE IF NOT EXISTS` pattern already in codebase
- **Phase 2 (Backend Routes):** Standard FastAPI routes matching existing patterns in `main.py`
- **Phase 3 (Runner Wiring):** Straightforward extension of `run_agent()` — patterns are clear from codebase inspection
- **Phase 5 (Auth Audit):** Documentation task; no new code patterns needed

---

## Confidence Assessment

| Area | Confidence | Notes |
|------|------------|-------|
| Stack | HIGH | All decisions verified against official docs, codebase inspection, and known CVEs. keyring vs. settings.json conflict resolved: settings.json wins for PyInstaller compatibility. |
| Features | HIGH | Prompt engineering guidance has multiple independent sources. Auth posture confirmed against Playwright official docs. Anti-features (pickle CVE) verified against actual incident reports. |
| Architecture | HIGH | Based on direct codebase inspection of all source files. Integration points, invariants, and build order derived from reading actual code, not inference. |
| Pitfalls | HIGH | CVE-2025-47241 has published CVSS score and advisory. PyInstaller Windows behavior verified against official docs and community reproduction reports. Config race pattern is well-understood. |

**Overall confidence:** HIGH

### Gaps to Address

- **CVE-2025-47241 patch verification in 0.12.6:** Research confirmed the vulnerability and the fix class (urllib.parse.urlparse vs. colon-split) but did not confirm the specific browser-use commit where the fix landed. Must inspect `browser_use/browser/profile.py` `_is_url_allowed()` in the installed 0.12.6 before Phase 5 ships.

- **ollama library vs. httpx for model discovery:** STACK.md recommends the `ollama` library; ARCHITECTURE.md notes the httpx path is already 90% done. Decide at Phase 2 start: add `ollama>=0.6.2` for typed ergonomics, or stay zero-new-dependencies with the existing httpx call.

- **`console=False` stdout redirect exact pattern on Windows 3.11 vs 3.12:** Both PITFALLS.md and STACK.md flag this, but the exact safe redirect pattern (open log file before uvicorn import vs. after) needs empirical validation on the Windows CI runner.

- **Prompt preset/guardrail conflict for job search login flows:** Job search presets may need to handle login flows while the guardrail says never submit credentials. The curated prompts in FEATURES.md scope this to unauthenticated collection only — validate this is acceptable to target users before Phase 4 ships.

---

## Sources

### Primary (HIGH confidence)
- Direct codebase inspection: `agent/db.py`, `agent/config.py`, `agent/runner.py`, `agent/main.py`, `agent/chrome_detect.py`, `agent/__main__.py`, `agent/paths.py`, `local-browser-agent.spec`
- [browser-use security advisory GHSA-x39x-9qw5-ghrf — CVE-2025-47241](https://github.com/browser-use/browser-use/security/advisories/GHSA-x39x-9qw5-ghrf)
- [PyInstaller Common Issues and Pitfalls](https://pyinstaller.org/en/stable/common-issues-and-pitfalls.html)
- [Ollama /api/tags endpoint documentation](https://docs.ollama.com/api/tags)
- [Ollama Python library (Context7 /ollama/ollama-python)](https://github.com/ollama/ollama-python)
- [platformdirs (Context7 /tox-dev/platformdirs)](https://github.com/tox-dev/platformdirs)
- [keyring PyInstaller issue #324](https://github.com/jaraco/keyring/issues/324)
- [Playwright Authentication Docs](https://playwright.dev/docs/auth)
- [browser-use System Prompt docs](https://docs.browser-use.com/customize/system-prompt)

### Secondary (MEDIUM confidence)
- [Kudelski Security: RCE on browser-use/web-ui](https://kudelskisecurity.com/research/getting-rce-on-browser-use-web-ui-ai-agent-instances)
- [OWASP 2025 Top 10 for LLM Applications: Prompt Injection at #1](https://www.obsidiansecurity.com/blog/prompt-injection)
- [PromptHub: Prompt Engineering for AI Agents](https://www.prompthub.us/blog/prompt-engineering-for-ai-agents)
- [browser-use/awesome-prompts GitHub](https://github.com/browser-use/awesome-prompts)
- [How to Fix Antivirus False Positives (pythonguis.com)](https://www.pythonguis.com/faq/problems-with-antivirus-software-and-pyinstaller/)
- [PyInstaller + uvicorn console=False issue (OneMinuteCode)](https://code.firstgear.co.kr/question/19392)
- [asyncio race conditions in FastAPI with global variables (DataSci Ocean)](https://datasciocean.com/en/other/fastapi-race-condition/)

### Tertiary (LOW confidence — needs validation during implementation)
- [browser-use task completion benchmarks (NxCode)](https://www.nxcode.io/resources/news/stagehand-vs-browser-use-vs-playwright-ai-browser-automation-2026)
- [Playwright MCP on WSL2 sandboxing](https://markaicode.com/playwright-mcp-wsl-chromium-sandboxing-fixes/)

---
*Research completed: 2026-05-18*
*Ready for roadmap: yes*

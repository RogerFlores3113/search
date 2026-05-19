# Architecture Research — v0.3.0 Settings, Presets, Windows

**Domain:** Local AI browser agent — settings persistence, Ollama discovery, prompt library, domain exclusion, Windows packaging
**Researched:** 2026-05-18
**Confidence:** HIGH — based on direct codebase inspection of all source files, verified against existing patterns

---

## Existing Architecture Baseline (v0.2.0)

```
┌─────────────────────────────────────────────────────────────────┐
│  Browser (User Chrome)                                           │
│  launched via cdp-use, headed, BrowserProfile.prohibited_domains │
└───────────────────────────┬─────────────────────────────────────┘
                            │ CDP over WebSocket
┌───────────────────────────▼─────────────────────────────────────┐
│  agent/runner.py — run_agent()                                   │
│  browser-use Agent → on_step_end=_log_step                       │
│  register_new_step_callback=_pre_step                            │
│  asyncio.Queue (data) + asyncio.Queue (control)                 │
│  _screenshot_loop background task                                │
└────────────┬──────────────────────────┬─────────────────────────┘
             │ put events               │ aiosqlite INSERT
┌────────────▼──────────┐  ┌───────────▼──────────────────────────┐
│  agent/main.py        │  │  agent/db.py                          │
│  FastAPI + HTMX + SSE │  │  runs table + additive ALTER TABLE    │
│  /run /pause /stop    │  │  DB_PATH = user_data_dir/history.db   │
│  /stream /runs        │  └──────────────────────────────────────┘
└────────────┬──────────┘
             │ SSE events
┌────────────▼──────────────────────────────────────────────────┐
│  Browser UI (localhost:8080)                                   │
│  HTMX swap targets + Alpine.js micro-interactions             │
│  agent/templates/index.html + agent/static/style.css          │
└──────────────────────────────────────────────────────────────┘

Persistence:
  agent/config.py   — pydantic-settings, reads .env / env vars
  data/history.db   — aiosqlite, run records
  data/training/    — JSONL training records
  data/secret.bin   — cookie signing key (itsdangerous)
```

### Key Invariants to Preserve

- `asyncio.Queue` is the **only** bridge between agent callbacks and the HTTP layer. Do not introduce threading.
- `BrowserProfile.prohibited_domains` is set **once** per `run_agent()` call from a merged domain set. No runtime mutation.
- `config` in `agent/config.py` is a **module-level singleton** (`config = Settings()`). Re-instantiation mid-run is wrong; mutation is the correct pattern when settings change.
- `_resource_path()` in `main.py` handles frozen vs dev path resolution for templates and static files. Any new bundled resource must follow this pattern.
- `DB_PATH` and `TRAINING_FILE` are patched in `__main__.redirect_data_paths()` for frozen mode. New files stored in `user_data_dir` must follow the same patch pattern.

---

## New Components: Integration Points

### 1. Settings Persistence

**Decision: SQLite table `settings` in the existing `history.db`.**

Do NOT use a separate JSON config file, and do not add `keyring` for API key storage.

Rationale:
- `keyring` requires a system keyring daemon (Secret Service on Linux, Keychain on macOS, Credential Locker on Windows). In a frozen `.app` / `.exe`, Keychain and Credential Locker work, but keyring adds a non-trivial dependency and its PyInstaller hidden-import story is unverified. The v0.3.0 scope does not warrant that complexity.
- API keys are already read from `.env` / env vars via pydantic-settings. The settings panel should write them back to the same `.env` file in `user_data_dir` (not the project root). This keeps the existing `Settings` load chain intact.
- A `settings` SQLite table handles everything else: Ollama host override, selected model, provider choice, active prompt library entry. The table is in the same `history.db` that `init_db()` already manages.

**Storage split:**

| Setting type | Storage | Reason |
|---|---|---|
| API keys (Anthropic, OpenAI) | `.env` file in `user_data_dir` | pydantic-settings already reads `.env`; writing back keeps the existing chain |
| Provider, model, Ollama host | `settings` SQLite table | UI-editable, non-sensitive, works with existing aiosqlite pattern |
| Active prompt library entry | `settings` SQLite table | Foreign key to `prompt_library` table |
| Domain exclusion additions | `settings` SQLite table (JSON column) | Simple list, low volume |

**New `init_db()` additions** (`agent/db.py`):

```python
await db.execute("""
    CREATE TABLE IF NOT EXISTS settings (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL
    )
""")

await db.execute("""
    CREATE TABLE IF NOT EXISTS prompt_library (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL UNIQUE,
        content TEXT NOT NULL,
        created_at TEXT NOT NULL,
        is_active INTEGER NOT NULL DEFAULT 0
    )
""")
```

Both tables are additive — `init_db()` is idempotent, so existing databases are safe.

**`.env` write pattern** for API keys:

```python
# agent/db.py (or new agent/settings_store.py)
def write_env_key(key: str, value: str) -> None:
    """Write/update a single key in user_data_dir/.env.
    Reads existing file, replaces line if key present, appends if not.
    """
    env_path = get_user_data_dir() / ".env"
    ...
```

After writing, call `config.model_validate(Settings())` to hot-reload the singleton — or simply update the relevant field directly on the module-level `config` object (pydantic models are mutable by default unless `model_config = ConfigDict(frozen=True)`, which the current config does not use).

**Integration with runner.py**: `run_agent()` reads `config.blocked_domains` and `config.provider` etc. at call time. If the settings panel updates `config` (or re-instantiates it) before the next `run_agent()` call, the new settings are used automatically. No changes to runner.py are required for this flow.

---

### 2. Ollama Model Discovery

**Already 90% done.** `runner.py:pre_flight_check()` already calls `GET /api/tags` via `httpx.AsyncClient` and parses the model list:

```python
resp = await client.get(f"{cfg.ollama_host}/api/tags")
models = [m["name"] for m in resp.json().get("models", [])]
```

**New: dedicated `/api/ollama-models` FastAPI route** in `main.py`:

```python
@app.get("/api/ollama-models")
async def ollama_models_endpoint():
    """Return list of locally available Ollama models.
    Called by the settings panel to populate the model picker.
    Returns {"models": [...], "error": null} or {"models": [], "error": "..."}
    """
```

Internally calls the same httpx pattern already in `pre_flight_check`. Returns JSON — the settings panel uses HTMX or a fetch() call to populate a `<select>`.

**Response shape from `/api/tags`** (HIGH confidence, verified from Ollama docs):

```json
{
  "models": [
    {
      "name": "qwen2.5vl:7b",
      "model": "qwen2.5vl:7b",
      "size": 4661211808,
      "details": {
        "parameter_size": "7B",
        "quantization_level": "Q4_0",
        "family": "qwen2"
      }
    }
  ]
}
```

Expose `name` and `details.parameter_size` in the UI dropdown. No Ollama library dependency needed — `httpx` is already in the dependency list.

**Integration point**: New route in `main.py`. No changes to `runner.py` or `config.py`.

---

### 3. Prompt Library

**Data model** (in `history.db` — see above):

```sql
CREATE TABLE IF NOT EXISTS prompt_library (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    content TEXT NOT NULL,
    created_at TEXT NOT NULL,
    is_active INTEGER NOT NULL DEFAULT 0
)
```

Only one entry should have `is_active = 1` at a time. Enforce this in the INSERT/UPDATE function, not via a DB constraint (SQLite partial unique index syntax is awkward; application-level enforcement is simpler).

**New CRUD functions** in `agent/db.py`:

```python
async def list_prompts() -> list[dict]: ...
async def upsert_prompt(name: str, content: str) -> int: ...
async def set_active_prompt(id: int) -> None: ...
async def delete_prompt(id: int) -> None: ...
async def get_active_prompt() -> dict | None: ...
```

**New FastAPI routes** in `main.py`:

```
GET  /api/prompts           → list all (for settings panel)
POST /api/prompts           → create/update (name + content form fields)
DELETE /api/prompts/{id}    → delete
POST /api/prompts/{id}/activate → set active
```

**Integration with runner.py**: `run_agent()` currently uses the hardcoded `GUARDRAIL_PROMPT` as `extend_system_message`. For prompt library integration, `run_agent()` needs to accept an optional `system_prompt` parameter or fetch the active prompt from DB at call time.

**Recommended**: fetch at call time, compose with GUARDRAIL_PROMPT:

```python
async def run_agent(task: str, queue=None, control_queue=None) -> None:
    active = await history_db.get_active_prompt()
    user_prompt = active["content"] if active else ""
    full_system = user_prompt + "\n" + GUARDRAIL_PROMPT if user_prompt else GUARDRAIL_PROMPT
    # pass full_system as extend_system_message to Agent()
```

GUARDRAIL_PROMPT must always be appended — it is a safety requirement, not a user preference. User prompts prepend; guardrails always trail.

**A/B testing note** (PROMPT-01): The data model supports it — store two named prompts, toggle `is_active`. True A/B (random per run) is a follow-on enhancement; v0.3.0 just needs single active prompt selection.

---

### 4. Domain Exclusion List

**Current state**: `config.blocked_domains` is a `set[str]` in `Settings` with hardcoded defaults covering banking and payment sites (10 entries). It is passed directly to `BrowserProfile.prohibited_domains` in `run_agent()`.

**v0.3.0 requirement**: Two-tier list — non-editable hardcoded safety defaults + user-extensible additions.

**Storage pattern**:

```python
# agent/config.py
SAFETY_DEFAULTS: frozenset[str] = frozenset({
    "chase.com", "wellsfargo.com", "bankofamerica.com",
    "citi.com", "usbank.com", "paypal.com", "venmo.com",
    "stripe.com", "square.com", "braintree.com",
    # v0.3.0 additions: gov, medical
    "irs.gov", "ssa.gov", "medicare.gov", "medicaid.gov",
})
```

User additions stored in the `settings` table as a JSON array under key `"user_blocked_domains"`:

```python
# agent/db.py
async def get_user_blocked_domains() -> set[str]:
    row = await get_setting("user_blocked_domains")
    return set(json.loads(row)) if row else set()

async def set_user_blocked_domains(domains: set[str]) -> None:
    await upsert_setting("user_blocked_domains", json.dumps(sorted(domains)))
```

**Merge at agent launch** in `run_agent()`:

```python
user_domains = await history_db.get_user_blocked_domains()
all_blocked = config.SAFETY_DEFAULTS | user_domains
profile = BrowserProfile(prohibited_domains=all_blocked, ...)
```

**Important**: `config.blocked_domains` in `Settings` becomes obsolete — `SAFETY_DEFAULTS` replaces it as a module-level constant (not a Settings field). This removes the `.env` parsing complexity noted in the existing `config.py` comment (`# pydantic-settings set[str] coercion from env var is unverified`).

**UI in settings panel**: Two sections — "Safety defaults (read-only)" listing `SAFETY_DEFAULTS`, and "Your additions" with add/remove UI. HTMX form submitting to `POST /api/blocked-domains`.

**New routes** in `main.py`:
```
GET  /api/blocked-domains       → {defaults: [...], user: [...]}
POST /api/blocked-domains       → add domain (form field: domain)
DELETE /api/blocked-domains/{domain} → remove user domain (cannot remove defaults)
```

---

### 5. Windows PyInstaller

**Key differences from macOS `.app`:**

| Area | macOS | Windows | Action required |
|------|-------|---------|-----------------|
| asyncio event loop | ProactorEventLoop (default, fine) | ProactorEventLoop (default on Win 3.8+, fine) | Add `multiprocessing.freeze_support()` call in `__main__.py` |
| Chrome path | `/Applications/Google Chrome.app/...` | `C:\Program Files\Google\Chrome\Application\chrome.exe` and `C:\Program Files (x86)\...` | Extend `chrome_detect.py` with Windows paths |
| Data directory | `~/Library/Application Support/local-browser-agent/` | `C:\Users\<user>\AppData\Local\local-browser-agent\` | platformdirs handles automatically — no code change |
| Bundle output | `.app` (BUNDLE step in spec) | `.exe` (no BUNDLE step) | Separate `local-browser-agent-windows.spec` |
| Codesign | `codesign --force --deep -s -` | Not required for initial release | Skip codesign step in Windows CI |
| console= | `False` (windowed .app) | `True` recommended for debugging initially, then `False` | Start with `True`, flip after smoke test |
| Path separator | `/` | `\` | platformdirs + pathlib.Path handle this; no raw string paths |
| subprocess CREATE_NO_WINDOW | N/A | Needed to suppress cmd windows when browser launches | Add `creationflags=subprocess.CREATE_NO_WINDOW` to any `subprocess.run()` calls |

**Required `__main__.py` additions for Windows**:

```python
import multiprocessing
import sys

def main() -> None:
    if sys.platform == "win32":
        multiprocessing.freeze_support()  # Required for PyInstaller onedir on Windows
    ...
```

This must be called before any multiprocessing usage. uvicorn's reload mode uses multiprocessing; the app uses `uvicorn.run()` (not `--reload`) so the risk is low, but `freeze_support()` is cheap and prevents an infinite spawn loop if this assumption ever changes.

**Windows `chrome_detect.py` extension**:

```python
CHROME_PATHS_WINDOWS = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
]

def chrome_is_installed() -> bool:
    if sys.platform == "darwin":
        return os.path.exists(CHROME_PATH_MACOS)
    if sys.platform == "win32":
        return any(os.path.exists(p) for p in CHROME_PATHS_WINDOWS)
    return True
```

**Windows spec file** (`local-browser-agent-windows.spec`):

```python
# Key differences from Mac spec:
# 1. No BUNDLE() step — Windows does not produce .app bundles
# 2. console=False for windowed .exe (no terminal popup)
# 3. Same hiddenimports as Mac spec

exe = EXE(
    pyz, a.scripts, a.binaries, a.zipfiles, a.datas,
    name="local-browser-agent",
    debug=False,
    upx=False,
    console=False,       # No terminal window
    # No exclude_binaries=True here — onefile embeds everything
)
# NO coll = COLLECT() step
# NO app = BUNDLE() step
```

**GitHub Actions Windows workflow** (`windows.yml`):

```yaml
jobs:
  build-windows:
    runs-on: windows-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v4
      - run: uv sync --frozen
      - run: uv run pyinstaller --clean --noconfirm local-browser-agent-windows.spec
      - uses: actions/upload-artifact@v4
        with:
          name: local-browser-agent-windows
          path: dist/local-browser-agent.exe
```

Trigger: same tag push pattern as the existing Mac CI workflow. Both workflows upload to the same GitHub Release as separate assets.

**Hidden imports to add for Windows**: The Mac spec's `hiddenimports` list is correct and sufficient. Windows may additionally need:

```python
"win32api",      # if any dependency uses pywin32 (low probability — nothing in current deps does)
"encodings",     # sometimes needed on Windows frozen builds
```

Validate by running `pyinstaller --debug=imports` and checking stderr for `ModuleNotFoundError` at startup.

**Onedir vs onefile**: Use onedir (the default, same as Mac). Onefile on Windows extracts to `%TEMP%` on each launch, causing Windows Defender false positives and slow cold starts. Onedir is a folder of files — distribute as a `.zip`, users extract and double-click the `.exe`. This matches the Mac distribution model (`.app` inside a `.zip`).

---

## Component Boundaries: New vs Modified

### New Files

| File | Purpose | Dependencies |
|------|---------|--------------|
| `agent/settings_store.py` (optional) | CRUD helpers for `settings` and `prompt_library` tables; could also go in `db.py` | `aiosqlite`, `agent/db.py` |
| `agent/templates/settings_fragment.html` | Settings panel HTML fragment (HTMX out-of-band swap) | Jinja2 |
| `local-browser-agent-windows.spec` | PyInstaller spec for Windows exe | PyInstaller |
| `build_scripts/build_windows.bat` | Local dev Windows build mirror of `build_mac.sh` | PyInstaller, uv |
| `.github/workflows/build-windows.yml` | CI workflow: tag push → Windows exe → GitHub Release | GitHub Actions |

### Modified Files

| File | What Changes | Why |
|------|-------------|-----|
| `agent/db.py` | Add `settings` and `prompt_library` table creation in `init_db()`; add CRUD functions | Settings persistence |
| `agent/config.py` | Extract `blocked_domains` into `SAFETY_DEFAULTS` frozenset constant; remove from `Settings` class | Two-tier domain exclusion |
| `agent/runner.py` | Merge `SAFETY_DEFAULTS | user_blocked_domains` before `BrowserProfile()`; fetch active prompt before `Agent()` | Domain exclusion + prompt library |
| `agent/main.py` | Add `/api/prompts`, `/api/blocked-domains`, `/api/ollama-models`, `/api/settings` routes; add settings panel render route | New settings API |
| `agent/chrome_detect.py` | Add Windows Chrome path detection | Windows packaging |
| `agent/__main__.py` | Add `multiprocessing.freeze_support()` for Windows | Windows PyInstaller |
| `agent/templates/index.html` | Add settings panel trigger button; add settings panel container | Settings UI |

### Unchanged Files (important)

| File | Why Unchanged |
|------|--------------|
| `agent/events.py` | No new SSE events needed for settings features |
| `agent/paths.py` | `get_user_data_dir()` via platformdirs already handles Windows correctly |
| `agent/launcher.py` | Browser open on localhost works the same on Windows |
| `local-browser-agent.spec` | Mac spec is unchanged |

---

## Data Flow: Settings Panel → Agent Run

```
User opens settings panel
    ↓
GET /api/settings        → reads settings table + returns current config
GET /api/ollama-models   → hits localhost:11434/api/tags → returns model list
GET /api/prompts         → reads prompt_library table
GET /api/blocked-domains → returns {defaults: SAFETY_DEFAULTS, user: user_blocked_domains}

User makes changes, submits form
    ↓
POST /api/settings       → writes to settings table; mutates config singleton
POST /api/prompts        → upserts prompt_library row
POST /api/blocked-domains → writes user_blocked_domains to settings table

User runs a task
    ↓
POST /run  →  run_agent(task)
               ├─ await history_db.get_user_blocked_domains()
               ├─ all_blocked = SAFETY_DEFAULTS | user_domains
               ├─ await history_db.get_active_prompt()
               ├─ full_system = user_prompt + GUARDRAIL_PROMPT
               ├─ profile = BrowserProfile(prohibited_domains=all_blocked, ...)
               └─ agent = Agent(..., extend_system_message=full_system)
```

The settings panel never touches `run_agent()` directly — it writes to DB and mutates the config singleton. `run_agent()` reads from those sources at call time. This keeps the existing asyncio.Queue-based event flow entirely intact.

---

## Settings Panel UI Architecture

**Pattern: HTMX out-of-band swap with a drawer overlay.**

The settings panel is a `<div>` rendered by a new Jinja2 template fragment (`settings_fragment.html`). It is injected into the main `index.html` layout on first click via `hx-get="/settings" hx-target="#settings-drawer" hx-swap="innerHTML"`.

Alpine.js manages the open/closed state with `x-show`:

```html
<!-- In index.html -->
<div id="settings-drawer" x-data="{open: false}">
  <div x-show="open" @keydown.escape.window="open=false">
    <!-- settings_fragment.html content goes here -->
  </div>
</div>
<button @click="$dispatch('open-settings')">Settings</button>
```

Each section within the panel (API keys, model picker, prompt library, domain exclusion) is a separate HTMX form that posts to its own `/api/*` endpoint. Responses return HTMX fragments that swap the relevant sub-section — no full page reload.

**The Ollama model picker** is populated via `hx-get="/api/ollama-models"` on settings panel open, with a `hx-indicator` spinner while the request is in flight. If Ollama is not running, the endpoint returns `{"models": [], "error": "Ollama unreachable"}` and the UI shows a helpful message instead of a broken dropdown.

---

## Build Order Recommendation

Order based on dependency graph and risk:

**Phase A — Foundation (unblocks everything)**
1. `init_db()` additions — `settings` and `prompt_library` tables. No UI, just schema. Test with existing test_db.py pattern.
2. CRUD functions in `db.py` — `get/set_setting`, `list/upsert/delete_prompt`, `get/set_user_blocked_domains`. Unit-testable in isolation.

**Phase B — Backend routes (before UI work)**
3. `/api/ollama-models` route — simplest new route; validates the httpx-to-Ollama pattern in the HTTP layer. Already tested indirectly by pre_flight_check.
4. `/api/settings` GET + POST — read/write the settings table; mutates config singleton.
5. `/api/prompts` CRUD routes.
6. `/api/blocked-domains` GET + POST + DELETE.

**Phase C — Runner wiring**
7. Domain exclusion merge in `run_agent()` — replaces `config.blocked_domains` with `SAFETY_DEFAULTS | user_domains`. Requires Phase A #2 complete.
8. Active prompt fetch in `run_agent()` — fetches active prompt and composes with GUARDRAIL_PROMPT. Requires Phase A #2 complete.

**Phase D — UI**
9. Settings panel drawer + all form sections. Requires Phase B complete so forms have working endpoints.
10. UI theme overhaul (dark green, badge colors) — pure CSS/template work, no backend dependency.

**Phase E — Windows packaging**
11. `chrome_detect.py` Windows extension — trivial, unblocked.
12. `__main__.py` `freeze_support()` addition — trivial, unblocked.
13. `local-browser-agent-windows.spec` — model off Mac spec with the documented differences.
14. `build_scripts/build_windows.bat` — local dev build script.
15. `.github/workflows/build-windows.yml` — CI workflow. Validate locally first (cross-compile from Windows runner is required — cannot build Windows .exe on macOS runner).

Windows packaging is independent of all other phases — it can be done in parallel with Phase D or after it. It is last in the recommended order because it has no blockers and is the least risky to defer.

---

## Anti-Patterns to Avoid

### Anti-Pattern 1: Config reload via re-instantiation mid-run

**What people do:** Call `config = Settings()` inside a route handler after writing new settings.
**Why it's wrong:** The module-level `config` singleton imported by `runner.py` is not updated — Python module imports are cached. Re-assignment inside a function creates a local binding, not a global one.
**Do this instead:** Mutate the existing singleton: `config.provider = new_value`. Or import and mutate: `from agent import config as cfg_module; cfg_module.config.provider = new_value`.

### Anti-Pattern 2: Merging blocked domains inside BrowserProfile at module load

**What people do:** Build the merged domain set at module level (e.g., as a module-level constant computed from config + DB at import time).
**Why it's wrong:** DB is async; `init_db()` has not run at import time. Module-level DB reads are impossible without a running event loop.
**Do this instead:** Merge inside `run_agent()` (async context, DB available): `user_domains = await history_db.get_user_blocked_domains()`.

### Anti-Pattern 3: PyInstaller onefile on Windows

**What people do:** Build with `--onefile` to produce a single `.exe` for simplicity.
**Why it's wrong:** On Windows, onefile extracts to `%TEMP%` on every launch — triggers Windows Defender scans, causes slow cold starts (5–15s), and breaks relative-path assumptions. Security tools often flag onefile bundles.
**Do this instead:** Use onedir (default). Distribute as a `.zip` archive containing the folder. Same user experience as Mac's `.app`-in-a-zip.

### Anti-Pattern 4: Writing API keys to the project root `.env`

**What people do:** Write settings from the UI back to `.env` in the current working directory.
**Why it's wrong:** In a frozen `.app`/`.exe`, the CWD is inside the bundle or the temp extraction folder — not writable, and wiped on update.
**Do this instead:** Write to `get_user_data_dir() / ".env"`. Then configure pydantic-settings to also search that path: `env_file=[str(get_user_data_dir() / ".env"), ".env"]` (list form, first match wins).

### Anti-Pattern 5: Prompt library replaces GUARDRAIL_PROMPT

**What people do:** Let users overwrite `extend_system_message` entirely with their custom prompt.
**Why it's wrong:** GUARDRAIL_PROMPT contains safety instructions that must always be present. A user who accidentally clears them could trigger payment or credential submissions.
**Do this instead:** Always concatenate: `extend_system_message = user_prompt + "\n\n" + GUARDRAIL_PROMPT`. GUARDRAIL_PROMPT trails every user prompt.

---

## Integration Point Reference Table — v0.3.0

| Feature | File | Integration Type | New or Modified |
|---------|------|-----------------|-----------------|
| Settings table + prompt_library table | `agent/db.py` | `CREATE TABLE IF NOT EXISTS` in `init_db()` | Modified |
| Settings CRUD | `agent/db.py` | New async functions | Modified |
| Prompt CRUD | `agent/db.py` | New async functions | Modified |
| User blocked domains read | `agent/db.py` | New async functions | Modified |
| SAFETY_DEFAULTS constant | `agent/config.py` | Module-level frozenset replacing `blocked_domains` field | Modified |
| Domain merge + prompt fetch | `agent/runner.py` | Top of `run_agent()`, before `BrowserProfile()` and `Agent()` | Modified |
| `/api/ollama-models` | `agent/main.py` | New GET route, httpx to localhost:11434/api/tags | Modified |
| `/api/settings` | `agent/main.py` | New GET/POST route | Modified |
| `/api/prompts` | `agent/main.py` | New GET/POST/DELETE routes | Modified |
| `/api/blocked-domains` | `agent/main.py` | New GET/POST/DELETE route | Modified |
| Settings panel HTML | `agent/templates/` | New fragment, HTMX drawer pattern | New |
| Windows Chrome detection | `agent/chrome_detect.py` | Extend existing `if sys.platform == "win32":` branch | Modified |
| freeze_support | `agent/__main__.py` | Add `multiprocessing.freeze_support()` for `win32` | Modified |
| Windows spec | `local-browser-agent-windows.spec` | New spec, no BUNDLE step, onedir | New |
| Windows CI | `.github/workflows/build-windows.yml` | New workflow, `runs-on: windows-latest` | New |

---

## Sources

- Direct codebase inspection: `agent/db.py`, `agent/config.py`, `agent/runner.py`, `agent/main.py`, `agent/chrome_detect.py`, `agent/__main__.py`, `agent/paths.py`, `local-browser-agent.spec`
- [Ollama /api/tags endpoint documentation](https://docs.ollama.com/api/tags) — response schema verified
- [PyInstaller Common Issues and Pitfalls](https://pyinstaller.org/en/stable/common-issues-and-pitfalls.html) — Windows onefile behavior, freeze_support requirement
- [Python asyncio platform support](https://docs.python.org/3/library/asyncio-platforms.html) — ProactorEventLoop as Windows default since 3.8
- [PyInstaller multiprocessing recipe](https://github.com/pyinstaller/pyinstaller/wiki/Recipe-Multiprocessing) — freeze_support pattern
- [iancleary/pyinstaller-fastapi](https://github.com/iancleary/pyinstaller-fastapi) — FastAPI + uvicorn + PyInstaller on Windows example
- [keyring PyPI](https://pypi.org/project/keyring/) — reviewed and ruled out for v0.3.0

---

*Architecture research for: local-browser-agent v0.3.0 settings, presets, Windows packaging*
*Researched: 2026-05-18*

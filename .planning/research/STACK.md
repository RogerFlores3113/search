# Stack Research — v0.3.0 Polish & Presets

**Project:** local-browser-agent
**Researched:** 2026-05-18
**Milestone:** v0.3.0 (settings panel, Ollama model discovery, Windows .exe, prompt library)
**Confidence:** HIGH

---

## What Changed From v0.2.0

This document covers **only additions and changes** for v0.3.0. The full validated stack from v0.1.0–v0.2.0 (browser-use, FastAPI, HTMX, SSE, asyncio.Queue, aiosqlite, PyInstaller 6.20.0, LiteLLM >=1.83.0) remains unchanged.

---

## New Dependencies Required

| Library | Version | Purpose | Why |
|---------|---------|---------|-----|
| ollama | >=0.6.2 | Ollama model discovery — list locally available models | Official Ollama Python client; `ollama.list()` returns full model metadata (name, size, family, parameter_size, quantization_level) from `GET /api/tags`; httpx-backed; 0.6.2 released 2026-04-29 |

**Everything else already exists in pyproject.toml:**
- `platformdirs>=4.9.6` — already a production dependency; use `user_config_path()` for settings JSON
- `PyInstaller==6.20.0` — already a dev dependency; same spec file approach extends to Windows
- `httpx>=0.27` — already present; use for Ollama health check before loading models

---

## Feature 1: Ollama Model Discovery

### Approach: `ollama` Python library (not raw httpx)

The project already calls ChatOllama directly. The `ollama` library is the official Python client maintained by the Ollama team (0.6.2, released April 2026).

**Why `ollama` library over raw `httpx` for model discovery:**
- `ollama.list()` returns typed `ListResponse` with `models: list[Model]`; each model has `.model`, `.size`, `.modified_at`, `.details.parameter_size`, `.details.quantization_level`, `.details.family` — exactly what the settings panel needs for display
- Handles Ollama connection errors with `ollama.ResponseError` — cleaner than parsing httpx 404s manually
- Already in the ecosystem (`ChatOllama` in browser-use depends on langchain-ollama which depends on ollama); adding `ollama` to `[project.dependencies]` adds no transitive weight

**Integration point:**

```python
import ollama

async def discover_ollama_models() -> list[dict]:
    """Returns list of available Ollama models, empty list if Ollama not running."""
    try:
        response = ollama.list()  # sync; wrap in asyncio.to_thread if needed
        return [
            {
                "name": m.model,
                "size_gb": round(m.size / 1e9, 1) if m.size else None,
                "family": m.details.family if m.details else None,
                "param_size": m.details.parameter_size if m.details else None,
            }
            for m in response.models
        ]
    except Exception:
        return []  # Ollama not running — graceful empty state
```

**Settings panel UX pattern:** On page load, call `GET /api/models/ollama` which calls `discover_ollama_models()`. If Ollama is not running, return `[]` and show "Ollama not detected — install from ollama.com" with a link. If running but no models pulled, return `[]` and show "No models found — run `ollama pull qwen2.5vl:7b`". Do not fail loudly; this is a settings helper.

**No Ollama dependency check needed at app start** — delay discovery to when the settings panel is opened. The agent already fails gracefully when ChatOllama can't connect.

---

## Feature 2: Settings Persistence

### Approach: platformdirs + JSON (already in stack, zero new dependencies)

`platformdirs>=4.9.6` is already a production dependency. Use `user_config_path()` to write a `settings.json` to the OS-appropriate user config directory.

**Why JSON over SQLite for settings:**
- Settings are a single flat/nested document (API keys, selected model, exclusion list, prompt library). JSON is direct; SQL is unnecessarily relational for this shape.
- Existing aiosqlite is for run history and steps — structured time-series. Settings are a singleton document.
- settings.json survives app reinstalls and PyInstaller rebuilds (written to user's AppData/Library, not inside the app bundle).

**Platform paths (verified via Context7):**
- macOS: `~/Library/Application Support/local-browser-agent/settings.json`
- Windows: `C:\Users\<user>\AppData\Local\local-browser-agent\settings.json`
- Linux: `~/.config/local-browser-agent/settings.json`

```python
from platformdirs import user_config_path
import json

CONFIG_PATH = user_config_path("local-browser-agent", ensure_exists=True) / "settings.json"

def load_settings() -> dict:
    if CONFIG_PATH.exists():
        return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    return {}

def save_settings(data: dict) -> None:
    CONFIG_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")
```

### API key storage: Do NOT use keyring

**keyring is not suitable for this project.** Reasons:

1. **PyInstaller incompatibility:** keyring >=12 in a bundled binary raises `RuntimeError: No recommended backend was available` because the OS keyring backends (Keychain, Windows Credential Manager) are not discoverable from within a frozen executable. The `keyrings.alt` fallback exists but stores credentials in plaintext anyway — defeating the purpose.
2. **Headless CI breakage:** GitHub Actions runners have no keyring daemon; keyring calls would fail during test runs.
3. **Unnecessary for this threat model:** The app is a single-user local tool. API keys in `settings.json` under `~/Library/Application Support/` are protected by OS user account permissions — the same protection level as `.env` files, VS Code settings, and all other dev tools that store API keys locally. The security model is "don't run on a shared machine."
4. **User expectation:** Users of local desktop tools expect to be able to inspect and edit their config file. Hiding keys in an opaque keychain adds friction without meaningful security gain for a single-user local app.

**Decision:** Store API keys in `settings.json`. Do not add `keyring` as a dependency.

---

## Feature 3: Settings Panel (HTMX + Alpine.js)

No new frontend libraries needed. The existing HTMX 2.x + Alpine.js 3.x pattern handles this cleanly.

**Settings panel pattern:**

- **Panel/modal open state:** Alpine.js `x-data="{ settingsOpen: false }"` on the body or layout component. The gear icon toggles `settingsOpen`. No HTMX needed for show/hide.
- **Loading model list:** `hx-get="/api/models/ollama" hx-trigger="revealed"` on the model select container — loads once when the settings panel is first opened.
- **Form submission:** `hx-post="/api/settings" hx-swap="none"` — save settings to server; Alpine.js can show a "Saved" toast on `htmx:afterRequest`.
- **Exclusion list editing:** Alpine.js `x-data="{ items: [] }"` with a simple `x-for` loop. Add/remove in client state, persist to server on save button click.
- **Tab switching (Ollama / API Keys / Exclusion List / Prompt Library):** Alpine.js `x-data="{ tab: 'ollama' }"` with `x-show="tab === 'ollama'"` on each panel section. No HTMX needed for tab switching — pure local state.

**The pattern is: HTMX for server round-trips, Alpine.js for client state (open/close, tab selection, list management).**

---

## Feature 4: Windows .exe Packaging

### PyInstaller version: already pinned at 6.20.0 (latest as of 2026-04-22)

The Mac `.app` build is validated. Windows `.exe` uses the same spec file approach with these additions and differences:

### Windows-specific spec file additions

```python
# In local-browser-agent.spec
# Windows: no codesign post-build hook here — sign with signtool.exe in CI
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    name='local-browser-agent',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,          # UPX increases AV false-positive rate — leave off
    console=False,      # --noconsole: no terminal window on double-click
    icon='assets/icon.ico',  # Windows requires .ico not .icns
)
```

### Critical Windows-only requirements

**1. `multiprocessing.freeze_support()` must be the first call in `__main__.py`:**

```python
import multiprocessing
multiprocessing.freeze_support()  # MUST be first on Windows

if __name__ == '__main__':
    # rest of startup
```

Windows uses `spawn` (not `fork`) as the default multiprocessing start method. Without `freeze_support()`, any code path touching multiprocessing (including asyncio internals in Python 3.12+) will trigger an infinite spawn loop and crash. This is a code change, not a spec file change.

**2. Console window:** Use `console=False` (equivalent to Mac `windowed=True`). With `console=False`, `sys.stdin/stdout/stderr` are `None` — ensure all logging goes to a file or the FastAPI/uvicorn log, never to stdout directly.

**3. Icon format:** Windows requires `.ico` (not `.icns`). Generate from the existing Mac icon asset using `pillow`:

```bash
python -c "from PIL import Image; img = Image.open('assets/icon.png'); img.save('assets/icon.ico')"
```

**4. UPX: do not use.** UPX compression increases Windows Defender false-positive rate. Leave `upx=False`.

**5. DLL path sanitization when launching Chrome:** PyInstaller's bootloader on Windows calls `SetDllDirectoryW` to restrict library search paths. Before spawning Chrome via Playwright, reset it:

```python
import ctypes, sys
if getattr(sys, 'frozen', False):  # only in PyInstaller bundle
    ctypes.windll.kernel32.SetDllDirectoryW(None)
```

### Windows Defender / SmartScreen

**The core problem:** Unsigned `.exe` files from PyInstaller are flagged by Windows Defender SmartScreen with "Windows protected your PC" on first run. This is a reputation issue, not a virus detection issue.

**Mitigations (in priority order):**

1. **EV code signing certificate** — eliminates SmartScreen warning immediately. Requires purchasing an EV certificate (~$300-500/year from DigiCert, GlobalSign, Sectigo). Use `signtool.exe` in GitHub Actions via Azure Key Vault or AWS KMS to avoid storing the private key in CI secrets.
2. **Standard OV certificate (budget option)** — reduces but does not eliminate SmartScreen warning. SmartScreen builds reputation over time once enough users run the signed binary.
3. **--onedir instead of --onefile** — a folder + `local-browser-agent.exe` looks less suspicious to AV scanners than a single self-extracting `.exe`. Worse UX but useful for initial testing.
4. **Reporting the false positive to Microsoft** — submit to https://www.microsoft.com/en-us/wdsi/filesubmission. Takes 1-3 days. Useful for unblocking beta users quickly.

**For v0.3.0 (portfolio target):** Start with unsigned exe + `--onedir` for testing, then sign with a standard OV cert if available. Document the SmartScreen click-through in the README. EV cert is the v1.0 production requirement.

### GitHub Actions Windows runner

```yaml
# In .github/workflows/release.yml — add alongside mac build job
build-windows:
  runs-on: windows-latest
  steps:
    - uses: actions/checkout@v4
    - uses: astral-sh/setup-uv@v5
    - run: uv sync
    - run: uv run pyinstaller local-browser-agent.spec
    - uses: actions/upload-artifact@v4
      with:
        name: local-browser-agent-windows
        path: dist/local-browser-agent/  # onedir output
```

**Do not use `windows-2019` runners** — use `windows-latest` (Windows Server 2022) for compatibility with Python 3.11+ and current MSVC runtime.

---

## What NOT to Add

| Avoid | Why | Use Instead |
|-------|-----|-------------|
| `keyring` | Fails in PyInstaller bundles; unnecessary for single-user local app threat model | settings.json with platformdirs |
| `python-dotenv` | App already uses pydantic-settings for env; adding dotenv creates two config systems | Keep pydantic-settings |
| `keyrings.alt` | Stores credentials in plaintext; defeats the purpose of keyring | settings.json |
| UPX compression | Increases Windows Defender false-positive rate | `upx=False` in spec |
| `windows-2019` GitHub runner | Outdated MSVC runtime; Python 3.11 compatibility edge cases | `windows-latest` |
| `Electron` for settings UI | 200MB+ binary, Node.js runtime, zero benefit over HTMX panel | Alpine.js tab panel |
| Separate settings database | SQLite is for time-series run history; settings is a singleton document | settings.json |

---

## Version Compatibility

| Package | Version | Notes |
|---------|---------|-------|
| ollama (Python) | >=0.6.2 | Sync + async client; `ollama.list()` returns `ListResponse`; requires Ollama server running at localhost:11434 |
| platformdirs | >=4.9.6 | Already in pyproject.toml; `user_config_path()` with `ensure_exists=True` creates dirs automatically |
| PyInstaller | ==6.20.0 | Already in dev deps; 6.20.0 is latest (2026-04-22); Windows numpy/pandas DLL collection fixed in 6.19.0+ |
| Python | >=3.11 | Windows runner must use 3.11 or 3.12; freeze_support() behavior changed in 3.12 (spawn is now default on macOS too) |

---

## Installation

```bash
# Add to [project.dependencies] in pyproject.toml
uv add "ollama>=0.6.2"

# platformdirs is already present — no change needed
# PyInstaller 6.20.0 is already in dev deps — no change needed
```

---

## Confidence Assessment

| Area | Confidence | Source |
|------|------------|--------|
| ollama.list() API shape | HIGH | Context7 /ollama/ollama-python verified; matches /api/tags REST docs |
| platformdirs user_config_path for settings JSON | HIGH | Context7 /tox-dev/platformdirs verified; already in pyproject.toml |
| keyring PyInstaller incompatibility | HIGH | GitHub issue jaraco/keyring#324; confirmed "No recommended backend" error in bundled binaries |
| multiprocessing.freeze_support() Windows requirement | HIGH | PyInstaller official docs; spawn-mode infinite loop is documented |
| Windows Defender SmartScreen on unsigned exe | HIGH | Multiple official and community sources; EV cert is the solution |
| UPX increases AV false-positive rate | HIGH | pythonguis.com PyInstaller AV guide; PyInstaller maintainer recommendations |
| PyInstaller 6.20.0 Windows DLL fixes | HIGH | Official changelog; numpy/pandas hooks fixed in 6.19.0+, 6.20.0 latest |
| console=False / sys.stdout=None on Windows | HIGH | PyInstaller official docs |
| ollama library already transitive dep via browser-use | MEDIUM | browser-use uses langchain-ollama which uses ollama; adding explicitly is safe and explicit |

---

## Sources

- [Ollama Python library (Context7 /ollama/ollama-python)](https://github.com/ollama/ollama-python) — `list()` API, ListResponse shape, 0.6.2 release date
- [Ollama REST API /api/tags](https://docs.ollama.com/api/tags) — model list endpoint documentation
- [platformdirs (Context7 /tox-dev/platformdirs)](https://github.com/tox-dev/platformdirs) — `user_config_path()` with `ensure_exists=True`, platform paths
- [keyring PyInstaller issue #324](https://github.com/jaraco/keyring/issues/324) — "No recommended backend" in frozen executables
- [PyInstaller Common Issues and Pitfalls](https://pyinstaller.org/en/stable/common-issues-and-pitfalls.html) — freeze_support, DLL path, console=False
- [PyInstaller Changelog 6.20.0](https://pyinstaller.org/en/stable/CHANGES.html) — Windows DLL fixes, CFG bootloader option
- [PyInstaller Recipe: Win Code Signing](https://github.com/pyinstaller/pyinstaller/wiki/Recipe-Win-Code-Signing) — signtool.exe integration
- [How to Fix Antivirus False Positives (pythonguis.com)](https://www.pythonguis.com/faq/problems-with-antivirus-software-and-pyinstaller/) — UPX, onedir, EV cert mitigations
- [Playwright Python PyInstaller hook](https://github.com/microsoft/playwright-python/blob/main/playwright/_impl/__pyinstaller/hook-playwright.async_api.py) — `collect_data_files("playwright")` built-in hook
- [HTMX + Alpine.js modal pattern (unfoldadmin.com)](https://unfoldadmin.com/blog/modal-windows-alpinejs-htmx/) — settings panel open/close pattern

---

*Stack research for: local-browser-agent v0.3.0*
*Researched: 2026-05-18*

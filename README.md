# local-browser-agent

A local AI browser agent — type any natural language task, the agent drives your Chrome and completes it. Streams every step live to a localhost web UI. All data stays on your machine.

## Features

- Natural language task input — type what you want, the agent does it
- Streams every step live to a localhost web UI
- Uses your installed Google Chrome (no bundled browser)
- All data stays local — API keys never leave your machine except for LLM calls
- Runs at your IP — not flagged as a bot

---

## Getting Started (Linux / WSL2 / Windows)

### Prerequisites

1. **[uv](https://docs.astral.sh/uv/)** — the only thing you need to install manually.

   ```bash
   # Linux / WSL2 / macOS
   curl -LsSf https://astral.sh/uv/install.sh | sh

   # Windows (PowerShell)
   powershell -c "irm https://astral.sh/uv/install.ps1 | iex"
   ```

2. **Google Chrome** — [download here](https://www.google.com/chrome/) if you don't have it.

3. **A local or cloud LLM.** For local inference, install [Ollama](https://ollama.com) and pull the recommended model:

   ```bash
   ollama pull qwen2.5vl:7b
   ```

   For API-based models (OpenAI, Anthropic, Gemini), you'll enter your key in the UI.

---

### Launch

```bash
# Clone
git clone https://github.com/rflores3113/local-browser-agent.git
cd local-browser-agent

# Linux / WSL2 / macOS
bash launch.sh

# Windows
launch.bat
```

On first run, `uv` downloads all dependencies automatically. Subsequent launches start in seconds. Your browser opens to **http://127.0.0.1:8080**.

---

### First-time Safety Disclaimer

On first launch, a disclaimer modal explains what the agent can and cannot do:

- It **will**: click, type, scroll, and navigate on any site you specify
- It **will not**: make purchases, submit payment information, or visit blocked domains

Click **"I understand — let's go"** to unlock the task prompt. The modal only appears once per browser profile.

---

### Where Your Data Lives

| Platform | Path |
|----------|------|
| Linux / WSL2 | `~/.local/share/local-browser-agent/` |
| Windows | `C:\Users\<you>\AppData\Local\local-browser-agent\local-browser-agent\` |
| macOS | `~/Library/Application Support/local-browser-agent/` |

Set `LBA_DATA_DIR` to use a different folder. When running from a source checkout the data lives in `<repo>/data/` instead.

Each folder contains `history.db` (session history), `training/runs.jsonl` (agent run logs), `secret.bin` (cookie-signing secret), and `app.log` (startup/error log).

**Settings and API keys.** `settings.json` (your provider settings, prompt library and the encrypted API key blobs) is stored in the platform config folder by default (`~/.config/local-browser-agent/` on Linux, `~/Library/Preferences/local-browser-agent/` or `~/Library/Application Support/local-browser-agent/` on macOS, `%APPDATA%\local-browser-agent\` on Windows). When `LBA_DATA_DIR` is set, `settings.json` moves into that folder too, so everything the app stores lives in one place. Existing settings are not copied over: move `settings.json` yourself if you want to keep them.

---

## Development

```bash
# Set up
uv sync

# Run
uv run python -m local_browser_agent.app

# Tests
uv run pytest tests/ -q
```

---

## macOS .app Bundle (planned)

Release builds of the Mac app are only ad-hoc signed (not notarized by Apple), so Gatekeeper warns the first time you open it ("cannot be opened because the developer cannot be verified"). To open it anyway, right-click (or Control-click) the app and choose **Open**, then confirm; or open it once, then go to **System Settings > Privacy & Security** and click **Open Anyway**. You only need to do this once.


A double-click `.app` bundle for macOS is planned for a future release. For now, macOS users can use `bash launch.sh` (requires uv).

## Use it as a library

The agent loop is also available as an importable package (`local_browser_agent`) with a CLI (`lba run`) and an MCP server (`lba mcp`):

```python
from local_browser_agent import AgentConfig, run_task_sync
result = run_task_sync("Open example.com and read the heading", AgentConfig.from_env())
print(result.status, result.final_result, result.errors)
```

See [docs/LIBRARY.md](docs/LIBRARY.md) for install, providers, safety policy, sinks, CLI exit codes and MCP setup, and [docs/EVALS.md](docs/EVALS.md) for the evaluation suite.

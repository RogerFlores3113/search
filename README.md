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

Each folder contains `history.db` (session history), `training/runs.jsonl` (agent run logs), and `app.log` (startup/error log).

---

## Development

```bash
# Set up
uv sync

# Run
uv run python -m agent

# Tests
uv run pytest tests/ -q
```

---

## macOS .app Bundle (planned)

A double-click `.app` bundle for macOS is planned for a future release. For now, macOS users can use `bash launch.sh` (requires uv).

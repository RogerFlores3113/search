# local-browser-agent

A consumer-grade local AI browser agent — download, double-click, done. The app drives your own Chrome from your machine using your residential IP. Type any natural language task; the agent completes it on any site. No Python, no terminal, no cloud required.

## Features

- Natural language task input — "find me a 2BR apartment under $2k in Austin" and the agent does it
- Streams every step live to a localhost web UI
- Uses your installed Google Chrome (no bundled browser)
- All data stays local — API keys never leave your machine except for LLM calls
- Runs on your machine at your IP — not flagged as a bot

---

## Installing on macOS

### Prerequisites

1. **Google Chrome** must be installed. Download it at [google.com/chrome](https://www.google.com/chrome/) if you don't have it.

2. **A local or cloud LLM** — for local inference, install [Ollama](https://ollama.com) and pull the recommended model:

   ```
   ollama pull qwen2.5vl:7b
   ```

   For API-based models (OpenAI, Anthropic, Gemini), you'll enter your API key in the UI.

---

### Download and Install

1. Go to the [GitHub Releases page](https://github.com/rflores3113/local-browser-agent/releases) and download `local-browser-agent-vX.Y.Z-mac.zip`.

2. Double-click the `.zip` to unzip it. You'll get `local-browser-agent.app`.

3. Optionally, drag `local-browser-agent.app` to your `/Applications` folder.

---

### First Launch: macOS Gatekeeper (Sequoia and later)

Because the app is not signed with an Apple Developer certificate, macOS Gatekeeper will block it on the first launch. This is expected — follow these steps **once per install**:

1. **Double-click** `local-browser-agent.app`. macOS will show a dialog:
   > "Apple could not verify 'local-browser-agent' is free of malware that may harm your Mac or compromise your privacy."

   Click **Done** (do not click "Move to Trash").

2. Open **System Settings** (the gear icon in your Dock or Apple menu → System Settings).

3. Click **Privacy & Security** in the sidebar.

4. Scroll down to the **Security** section. You will see:
   > "local-browser-agent was blocked to protect your Mac."

   Click **Open Anyway**.

5. Authenticate with **Touch ID** or your password when prompted.

6. macOS shows a final confirmation dialog — click **Open**.

7. The app launches and your default browser automatically opens to **http://127.0.0.1:8080** within a few seconds.

**You only need to do this once.** Subsequent launches work with a normal double-click.

#### Older macOS (Sonoma and earlier)

On older macOS versions, the right-click → "Open" shortcut used to bypass Gatekeeper for unsigned apps. **This no longer works reliably on modern macOS.** Use the System Settings path above on any macOS version.

---

### What You'll See

On first launch, a **disclaimer modal** appears explaining what the agent can and cannot do:

- It **will**: click, type, scroll, and navigate on any site you specify
- It **will not**: make purchases, submit payment information, or visit its blocklist sites

Click **"I understand — let's go"** to accept and unlock the task prompt. This disclaimer only appears once per browser profile.

---

### Where Your Data Lives

All app data is stored in:

```
~/Library/Application Support/local-browser-agent/
```

That folder contains:

| File | Contents |
|------|----------|
| `history.db` | Session history and results |
| `training/runs.jsonl` | Agent run logs (opt-in training data) |
| `app.log` | Application startup and error log |

**To fully reset the app:** delete `~/Library/Application Support/local-browser-agent/` and clear `localStorage` in your browser (DevTools → Application → Local Storage → delete `disclaimer_accepted`).

---

## Development

The project uses [uv](https://docs.astral.sh/uv/) for dependency management.

```bash
# Clone and set up
git clone https://github.com/rflores3113/local-browser-agent.git
cd local-browser-agent
uv sync

# Run in development mode
uv run python -m agent

# Run tests
uv run pytest tests/ -q
```

### Building the macOS App Locally

```bash
# One-liner: builds, signs, and zips the .app
bash build_scripts/build_mac.sh
# Output: dist/local-browser-agent-dev-mac.zip
```

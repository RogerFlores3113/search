<!-- GSD:project-start source:PROJECT.md -->
## Project

**local-browser-agent**

A consumer-grade local AI browser agent — download, double-click, done. The app drives the user's own Chrome from their machine and residential IP, the LLM has full browser control (click, type, scroll, navigate), and every step streams live to a localhost web UI. User types any natural language task; the agent completes it on any site. No Python, no terminal, no cloud required.

**Core Value:** User types any natural language task, the agent opens Chrome and completes it — a general-purpose agentic loop that works on arbitrary sites before structured presets are layered on top.

### Constraints

- **Tech stack**: Python — browser-use, LiteLLM, Playwright are all Python; no reason to deviate
- **Distribution**: Bundled native app — `.app` (Mac) and `.exe` (Windows) via PyInstaller or Briefcase. Double-click to launch, zero dependencies for end users. Built and published via GitHub Actions → GitHub Releases. Developer workflow uses `uv`.
- **Browser**: User's installed Google Chrome via `playwright.chromium.launch(channel="chrome")`. No Chromium download bundled. Headed (visible), residential IP, real browser fingerprint — not flagged as bot. Fallback: friendly prompt to install Chrome if not found.
- **Performance**: Minimize overhead — running Playwright + an LLM is already CPU/RAM intensive; UI must be lightweight
- **Security**: No cloud component; user's API keys stay local; no data leaves the machine except LLM API calls
- **Scope**: v1 is the general-purpose loop — prove it works on any site before building structured presets
<!-- GSD:project-end -->

<!-- GSD:stack-start source:research/STACK.md -->
## Technology Stack

## Recommended Stack
### Core Agentic Loop
| Technology | Version | Purpose | Why |
|------------|---------|---------|-----|
| browser-use | 0.12.6 | Agentic browser loop engine | Python-native, Playwright-backed, multi-provider LLM support, active development (123 releases), MIT license |
| playwright (python) | >=1.49 (browser-use installs this) | Browser control underneath browser-use | Managed by browser-use; do not pin separately |
| Python | >=3.11, <4.0 | Runtime | Required by browser-use; matches Apple Silicon + modern NVIDIA setups |
### LLM Provider Abstraction
| Technology | Version | Purpose | Why |
|------------|---------|---------|-----|
| litellm | >=1.83.0, pinned | Provider abstraction for API models (Anthropic, OpenAI, Gemini) | 100+ providers, OpenAI-compatible interface, vision support; pin above 1.82.6 to avoid the March 2026 backdoor incident |
| ChatOllama (via langchain-community or browser-use native) | latest | Ollama local model integration | browser-use accepts ChatOllama directly; no proxy layer needed for local inference |
### Vision Models (Local Inference via Ollama)
| Model | Size | Purpose | Why |
|-------|------|---------|-----|
| qwen2.5vl:7b | ~7B params | Primary local vision model for screenshot-driven navigation | Explicitly designed for computer use/agentic tasks on screenshots; substantially outperforms LLaVA on structured web content; available via `ollama pull qwen2.5vl` |
| qwen2.5vl:3b | ~3B params | Fallback for lower-VRAM machines (<8GB) | Smaller footprint when 7B won't fit in available VRAM |
| moondream2 | ~1.9B params | Fast path / development testing only | Fastest option; 1.9B means usable on CPU-only; accuracy insufficient for production navigation |
### Web UI
| Technology | Version | Purpose | Why |
|------------|---------|---------|-----|
| FastAPI | >=0.115 | HTTP server and SSE streaming | First-class async support, EventSourceResponse for SSE, minimal overhead |
| Jinja2 | >=3.1 | Server-side HTML rendering | No build step, no Node.js toolchain; pairs naturally with HTMX |
| HTMX | 2.x (CDN) | Dynamic UI updates without JavaScript framework | 30-40KB total JS payload vs 100-300KB for React; zero build tools; SSE swap target works natively |
| Alpine.js | 3.x (CDN) | Minimal client-side interactivity (spinners, toggle states) | Fills the gap HTMX leaves for micro-interactions; no build step |
| uvicorn | >=0.30 | ASGI server | Standard FastAPI server; `uvicorn.run()` for programmatic launch from Python |
### Fast Path (Non-JS Sites)
| Technology | Version | Purpose | Why |
|------------|---------|---------|-----|
| httpx | >=0.27 | Async HTTP for Craigslist/Zumper scraping | Already a FastAPI ecosystem tool; async-native; replaces requests |
| BeautifulSoup4 | >=4.12 | HTML parsing for fast-path scraper | Well-tested, minimal; only needed for non-JS path |
### Storage / Output
| Technology | Version | Purpose | Why |
|------------|---------|---------|-----|
| SQLite (via aiosqlite) | >=0.20 | Session and result persistence | Zero infrastructure; local-only; aiosqlite for async FastAPI |
| openpyxl | >=3.1 | Excel (.xlsx) export | Standard Python xlsx library; no Java/external runtime |
### Package Management and Distribution
| Technology | Version | Purpose | Why |
|------------|---------|---------|-----|
| uv | latest | Dependency management and virtual environments | Rust-native speed; cross-platform lockfiles; `uv run` for launch scripts without manual venv activation; replaces pip+venv for this project |
| pyproject.toml | PEP 621 | Project metadata and dependency declaration | uv-native; clean single source of truth |
# launch.sh (Mac/Linux)
# launch.bat (Windows)
## Alternatives Considered
| Category | Recommended | Alternative | Why Not |
|----------|-------------|-------------|---------|
| Agentic loop | browser-use | Stagehand | TypeScript-only — project is Python; Stagehand's v3 removed Playwright dependency (CDP-native) making Python interop impossible without subprocess hacks |
| Agentic loop | browser-use | Raw Playwright + custom loop | Months of engineering to replicate what browser-use provides: DOM extraction, element interaction, error recovery, multi-LLM support; not justified for v1 |
| LLM abstraction | litellm (for API) + ChatOllama (local) | OpenAI SDK only | Would lock out Anthropic, Gemini, Ollama; BYOM is a core feature requirement |
| Local vision model | qwen2.5vl:7b | LLaVA 7B | LLaVA underperforms on structured web content; Qwen2.5-VL was explicitly trained for computer/phone use including web navigation |
| Local vision model | qwen2.5vl:7b | llama3.2-vision:11b | LiteLLM had documented issues processing Llama 3.2 Vision images (interpreted as text); Qwen2.5-VL has better structured document/screenshot handling |
| UI framework | FastAPI + HTMX + SSE | FastAPI + React/Vite | React requires Node.js, build pipeline, npm, 100-300KB JS payload; HTMX delivers same UX with 30-40KB, zero build tooling |
| UI framework | FastAPI + HTMX + SSE | WebSockets | SSE is simpler for one-directional agent log streaming; no reconnection logic needed in client; browser handles reconnect natively |
| Package manager | uv | Poetry | uv is faster, handles Python version management, cross-platform lockfile is standard; Poetry is fine but slower and less integrated |
| Distribution | uv run launch script | Electron | Electron adds 200MB+ binary, Chromium duplication, Node.js runtime; localhost in system browser is sufficient |
| Distribution | uv run launch script | PyInstaller | PyInstaller bundles break frequently on dependency updates; uv is the cleaner local-first approach |
## Why browser-use (Not Stagehand, Not Raw Playwright)
- browser-use is 15-30x slower than deterministic Playwright (15-30 seconds per multi-step task). This is expected — an LLM is deciding every action. The hybrid fast path (httpx for Craigslist/Zumper) mitigates this for non-JS sites.
- litellm was removed from core dependencies (browser-use 0.12.5) due to the March 2026 supply chain incident. Install litellm separately, pin to `>=1.83.0`, and use `ChatLiteLLM` for API providers. For Ollama, use `ChatOllama` directly — no litellm intermediary needed.
- Chrome memory usage is high when running many parallel agents. This project is single-user, single-session, so it is a non-issue for v1.
## Installation
# Install uv (once per machine)
# Windows: powershell -c "irm https://astral.sh/uv/install.ps1 | iex"
# Project setup
# LiteLLM for API providers — pin explicitly to avoid re-exposing to supply chain risk
# Playwright browsers (run once after install)
# Pull the recommended vision model
# Optional fallback
## Confidence Levels
| Area | Confidence | Notes |
|------|------------|-------|
| browser-use as loop engine | HIGH | Active project, 0.12.6 released April 2026, documented Ollama + vision support, Python-native |
| LiteLLM for API provider abstraction | HIGH | Confirmed Ollama support; vision model OpenAI-format passthrough works; pin away from 1.82.7/1.82.8 |
| Qwen2.5-VL as primary local vision model | HIGH | Explicitly designed for computer use on screenshots; available in Ollama; outperforms LLaVA on structured web content |
| FastAPI + HTMX + SSE | HIGH | Well-documented pattern; EventSourceResponse in FastAPI; HTMX SSE extension is production-stable |
| uv for distribution | HIGH | Cross-platform, active Astral project, PEP 723 inline scripts, clean lockfiles |
| LiteLLM vision passthrough for newer models | MEDIUM | Core vision support is documented; edge cases exist with newer Ollama vision models (Llama 3.2 Vision had issues) — Qwen2.5-VL avoids these |
| browser-use task completion rate | MEDIUM | Benchmarks (~72-78%) are from third-party comparison articles, not browser-use's own benchmarks; real-world rate on apartment sites unknown |
## Sources
- [browser-use GitHub](https://github.com/browser-use/browser-use) — version 0.12.6, Python requirements, Ollama integration
- [browser-use Supported Models](https://docs.browser-use.com/open-source/supported-models) — 15+ providers, Ollama via ChatOllama, Qwen vision notes
- [Stagehand vs Browser Use vs Playwright (NxCode)](https://www.nxcode.io/resources/news/stagehand-vs-browser-use-vs-playwright-ai-browser-automation-2026) — task completion benchmarks, pitfalls
- [LiteLLM Ollama docs](https://docs.litellm.ai/docs/providers/ollama) — Ollama vision model integration
- [LiteLLM Security Update March 2026](https://docs.litellm.ai/blog/security-update-march-2026) — supply chain attack, safe versions
- [Qwen2.5-VL Ollama library](https://ollama.com/library/qwen2.5vl) — model availability and sizes
- [Qwen2.5-VL blog post](https://qwenlm.github.io/blog/qwen2.5-vl/) — computer use / agentic capabilities
- [FastAPI + HTMX guide (testdriven.io)](https://testdriven.io/blog/fastapi-htmx/) — SSE pattern, no-build approach
- [uv documentation](https://docs.astral.sh/uv/) — cross-platform distribution, PEP 723 scripts
- [LiteLLM supply chain attack (Trend Micro)](https://www.trendmicro.com/en_us/research/26/c/inside-litellm-supply-chain-compromise.html) — attack scope and recommended remediation
<!-- GSD:stack-end -->

<!-- GSD:conventions-start source:CONVENTIONS.md -->
## Conventions

Conventions not yet established. Will populate as patterns emerge during development.
<!-- GSD:conventions-end -->

<!-- GSD:architecture-start source:ARCHITECTURE.md -->
## Architecture

Architecture not yet mapped. Follow existing patterns found in the codebase.
<!-- GSD:architecture-end -->

<!-- GSD:skills-start source:skills/ -->
## Project Skills

No project skills found. Add skills to any of: `.claude/skills/`, `.agents/skills/`, `.cursor/skills/`, `.github/skills/`, or `.codex/skills/` with a `SKILL.md` index file.
<!-- GSD:skills-end -->

<!-- GSD:workflow-start source:GSD defaults -->
## GSD Workflow Enforcement

Before using Edit, Write, or other file-changing tools, start work through a GSD command so planning artifacts and execution context stay in sync.

Use these entry points:
- `/gsd-quick` for small fixes, doc updates, and ad-hoc tasks
- `/gsd-debug` for investigation and bug fixing
- `/gsd-execute-phase` for planned phase work

Do not make direct repo edits outside a GSD workflow unless the user explicitly asks to bypass it.
<!-- GSD:workflow-end -->



<!-- GSD:profile-start -->
## Developer Profile

> Profile not yet configured. Run `/gsd-profile-user` to generate your developer profile.
> This section is managed by `generate-claude-profile` -- do not edit manually.
<!-- GSD:profile-end -->

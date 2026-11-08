# Using local-browser-agent as a library

`local_browser_agent` is the agent loop (browser-use + your Chrome) as an importable package, with a
CLI (`lba`) and an MCP server. Importing it reads no config, touches no disk and uses no network
(it only sets `ANONYMIZED_TELEMETRY=false` and `BROWSER_USE_CLOUD_SYNC=false` as defaults).

## Install

```bash
uv add "local-browser-agent @ git+https://github.com/RogerFlores3113/search"
# with the MCP server:
uv add "local-browser-agent[mcp] @ git+https://github.com/RogerFlores3113/search"
```

You need Google Chrome installed (or set `BrowserConfig.executable_path` / `cdp_url`). Browsers are not downloaded.

## Quickstart

```python
import asyncio
from local_browser_agent import AgentConfig, ModelConfig, run_task

config = AgentConfig(model=ModelConfig(provider="anthropic", api_key="sk-ant-..."), max_steps=15)
result = asyncio.run(run_task("Find the cheapest USB-C cable on example-shop.test", config))
print(result.status, result.final_result)
```

`run_task_sync(...)` is the same call wrapped in `asyncio.run`. For control (pause/resume/stop), use
`BrowserAgent(config, sinks=..., approval=...)` and `await agent.run(task, start_url=None)`.
`AgentConfig.from_env()` builds a config from `LBA_*` variables (`LBA_PROVIDER`, `LBA_MODEL`,
`LBA_API_KEY`, `LBA_BASE_URL`, `LBA_HEADLESS`, `LBA_CDP_URL`, `LBA_MAX_STEPS`, `LBA_TIMEOUT_S`,
`LBA_ALLOWED_DOMAINS`, ...); `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` are used when the provider matches.
See `examples/use_as_library.py`.

## Providers

| provider | notes |
|---|---|
| `ollama` (default) | default model `qwen2.5vl:7b`; `base_url` is the Ollama host; `num_ctx=32000` |
| `anthropic` | default `claude-sonnet-4-5`; needs `api_key` |
| `openai` | default `gpt-4o`; needs `api_key` |
| `openai_compatible` | any OpenAI-style endpoint; needs `base_url` and `model` |
| `litellm` | any LiteLLM model string, e.g. `model="gemini/gemini-2.0-flash"` |

`ModelConfig.extra` is passed to the provider constructor (for Ollama it is merged into `ollama_options`).
Register your own:

```python
from local_browser_agent import ModelConfig, register_provider
from browser_use import ChatOpenAI

register_provider("my-gateway", lambda cfg: ChatOpenAI(model=cfg.model or "x", base_url="https://gw/v1",
                                                         api_key=cfg.api_key.get_secret_value()))
config = AgentConfig(model=ModelConfig(provider="my-gateway", api_key="..."))
```

`register_provider(name, factory, default_model=None)`; the factory takes a `ModelConfig` and returns a
browser-use chat model. An unknown provider raises `ValueError` listing the known ones. API keys are
`SecretStr` and never appear in `repr`, logs or `RunResult`. `await check_provider(model_config)` is an
optional pre-flight check (raises `PreFlightError`).

## Browser options

`BrowserConfig(headless=False, channel="chrome", executable_path=None, cdp_url=None, user_data_dir=None,
window_width=1280, window_height=800, llm_screenshot_width=1024, llm_screenshot_height=640, keep_alive=False)`

- **Attach to a running browser:** start Chrome with `--remote-debugging-port=9222` and set
  `BrowserConfig(cdp_url="http://127.0.0.1:9222")`. The agent attaches and does not kill your browser at the end.
- `keep_alive=True` also leaves a launched browser open after the run.
- `user_data_dir` reuses a Chrome profile (logins). Use a dedicated directory.

## Safety policy

`SafetyPolicy(blocked_domains, allowed_domains=None, guardrail_prompt=GUARDRAIL_PROMPT, gate_commerce_clicks=True, commerce_patterns=[...])`

- `blocked_domains` always includes `SAFETY_DEFAULTS` (banks, payments, government, medical, password managers); extra entries are added, none can be removed.
- `allowed_domains` restricts navigation to those domains.
- The guardrail prompt is appended to the system prompt.
- **Commerce gate:** click actions whose target label matches a commerce pattern ("Buy now", "Checkout", "Place order", "Pay", ...) are blocked in the tool layer, independent of the model. If you pass `approval=async (ActionRequest) -> bool`, it is asked first (`ActionRequest` has `action_name, params, element_label, url`); returning `True` lets the click through. Without a callback the click is blocked, the agent gets an error, and the attempt is listed in `RunResult.blocked_actions`.
- The element label is read from the accessibility name / aria-label / text of the clicked element via `browser_session.get_element_by_index`; coordinate clicks and unlabeled elements cannot be gated.

## Sinks and tracing

A sink is any `async def sink(event)`. Events: `StateEvent, ModelInfoEvent, ThoughtEvent, ActionDetailEvent, ProgressEvent, TokenEvent, ScreenshotEvent, SummaryEvent, ErrorEvent, DoneEvent`. A failing sink never crashes a run.

- `QueueSink(data_q, control_q=None)`: lossy `put_nowait` for data events; lifecycle events (state, model_info, summary, error_msg, done) block up to 2s.
- `JsonlTraceSink(path, include_screenshots=False)`: one JSON line per event.
- `CallbackSink(fn)`: sync or async function.

The screenshot loop only runs when at least one sink wants screenshots (a trace-only sink does not).

## RunResult

`run_id, task, status ("success"|"failed"|"error"|"timeout"|"stopped"), success (bool|None), final_result, steps (list of StepRecord: index, action_type, target_label, value, url, error, duration_ms), step_count, duration_s, cost_usd (None for Ollama), errors, urls_visited, blocked_actions`; `.to_dict()` gives plain JSON-able data.

## CLI

```bash
uv run lba run "Open example.com and read the heading" --provider anthropic --headless --max-steps 10 --json --trace run.jsonl
uv run lba run "..." --cdp-url http://127.0.0.1:9222 --start-url https://example.com
uv run lba mcp          # stdio MCP server
uv run lba eval ...     # evaluation suite (when installed)
```

`lba run` exits 0 on success, 1 on failed/error/timeout. It runs a provider pre-flight check unless `--no-preflight`.

## MCP server

Tools: `run_browser_task(task, start_url?, max_steps?, allowed_domains?)` (one run at a time; a concurrent call returns an error dict) and `get_agent_config()` (no secrets). Configuration comes from `LBA_*` environment variables.

```bash
claude mcp add local-browser-agent -e LBA_PROVIDER=anthropic -e ANTHROPIC_API_KEY=sk-ant-... -- uv run lba mcp
```

Claude Desktop (`claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "local-browser-agent": {
      "command": "uv",
      "args": ["run", "--directory", "/path/to/your/project", "lba", "mcp"],
      "env": { "LBA_PROVIDER": "anthropic", "ANTHROPIC_API_KEY": "sk-ant-..." }
    }
  }
}
```

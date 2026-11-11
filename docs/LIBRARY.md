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

A sink is any `async def sink(event)`. Events: `StateEvent, ModelInfoEvent, ThoughtEvent, ActionDetailEvent, ProgressEvent, TokenEvent, ScreenshotEvent, SummaryEvent, ErrorEvent, DoneEvent, HumanNeededEvent, StepCompletedEvent`. A failing sink never crashes a run.

- `QueueSink(data_q, control_q=None)`: lossy `put_nowait` for data events; lifecycle events (state, model_info, summary, error_msg, done) block up to 2s.
- `JsonlTraceSink(path, include_screenshots=False)`: one JSON line per event, appended to the file (an existing file is not truncated); each record has `ts` (UTC ISO 8601) and `run_id` (uuid4 per sink).
- `CallbackSink(fn)`: sync or async function.

The screenshot loop only runs when at least one sink wants screenshots (a trace-only sink does not).

`StepCompletedEvent` (run_id, step, screenshot_b64, action fields, thoughts, tokens, cost, duration_ms, error,
run_has_errors) is delivered only to sinks that set `wants_step_events = True`; the built-in sinks do not, so
it never reaches a UI queue. Use it to build a training/trace sink (the web app's `local_browser_agent/app/training_sink.py` does).
`BrowserAgent(..., preflight=async fn)` runs a check after the start events and before the browser is built;
an exception ends the run with status `"error"`. `agent.is_active` / `agent.is_paused` report control state.

## CAPTCHA / human verification

The agent never tries to solve a CAPTCHA. When a step's error text mentions one (`local_browser_agent.captcha.CAPTCHA_KEYWORDS`:
captcha, recaptcha, hcaptcha, cloudflare, bot detection, access denied, verify you are human, ...), it emits
`HumanNeededEvent(reason="captcha", url, message)` and then follows `AgentConfig.on_captcha`:

- `"fail"` (default): the run stops; `RunResult.status == "failed"` and `errors` contains
  "Human verification required (CAPTCHA or bot check detected at <url>)".
- `"pause"`: the agent pauses (`StateEvent("paused")`) and waits. Solve it in the visible browser, then call
  `agent.resume()` to continue, or `agent.stop()` to end the run (status `"stopped"`). `timeout_s` keeps
  counting while paused. The web app uses `"pause"`; its Resume button calls `resume()`.

## RunResult

`run_id, task, status ("success"|"failed"|"error"|"timeout"|"stopped"), success (bool|None), final_result, steps (list of StepRecord: index, action_type, target_label, value, url, error, duration_ms), step_count, duration_s, cost_usd (None for Ollama), errors, urls_visited, blocked_actions`; `.to_dict()` gives plain JSON-able data.

## CLI

```bash
uv run lba --version
uv run lba run "Open example.com and read the heading" --provider anthropic --headless --max-steps 10 --json --trace run.jsonl
uv run lba run "..." --cdp-url http://127.0.0.1:9222 --start-url https://example.com
uv run lba run "..." -q                 # only errors on stderr
uv run lba run "..." --log-level debug  # debug | info | warning | error
uv run lba mcp          # stdio MCP server (quiet stderr by default; -q / --log-level also work)
uv run lba eval ...     # evaluation suite (when installed)
```

**Exit codes:** `0` success; `1` the run failed, errored, timed out, or the pre-flight check failed; `2` usage or
configuration error (invalid flags / `LBA_*` values, or `lba eval` unavailable); `130` interrupted (Ctrl-C).

**Output streams:** with `--json`, stdout is always one JSON document shaped like `RunResult`, including when
pre-flight fails (then `status` is `"error"`, `success` is `null`, `errors` holds the message, `steps` is empty);
the human-readable message goes to stderr. Without `--json`, stdout holds the human summary and diagnostics go
to stderr. Logs always go to stderr; `--json` defaults to `warning` level, otherwise `info`; ANSI colour is
stripped when stderr is not a terminal.

**Pre-flight:** unless `--no-preflight`, `lba run` checks the provider first. For `ollama` it queries the local
server; for `anthropic` and `openai` it makes a **live API call** (listing models) with your key, so it needs
network access and can fail on a bad key or an outage. Chrome-not-found is also reported as a pre-flight error.

**Trace (`--trace PATH`):** `JsonlTraceSink` *appends* to an existing file (it never truncates), one JSON object
per event. Each record has `ts` (ISO 8601, UTC) and `run_id` (a uuid4 per sink, i.e. per CLI invocation), so
several runs can share a file. A pre-flight failure still writes `error_msg`, `state: error` and `done` events.

## MCP server

Tools: `run_browser_task(task, start_url?, max_steps?, allowed_domains?)` and `get_agent_config()` (no secrets;
API key shown as `set`, URL credentials/tokens and `model.extra` values redacted).

- One task at a time; a concurrent call fails at once with a `busy` error.
- `max_steps` must be 1-200; `allowed_domains`, if given, must be non-empty. Invalid input is rejected.
- If the server has `LBA_ALLOWED_DOMAINS`, a call's `allowed_domains` can only **narrow** it: a requested domain
  is kept only if it equals or is a subdomain of a server domain; an empty result returns an error and nothing runs.
  Without a server allowlist the call's list is used. Blocked domains (banks, payments, ...) always stay blocked.
- Any status other than `success` is returned with `isError: true`; the `RunResult` dict is in `structuredContent`
  (and the text content).

Configuration comes from `LBA_*` environment variables: `LBA_PROVIDER`, `LBA_MODEL`, `LBA_API_KEY`, `LBA_BASE_URL`,
`LBA_HEADLESS`, `LBA_CDP_URL`, `LBA_MAX_STEPS`, `LBA_TIMEOUT_S`, `LBA_ALLOWED_DOMAINS` (comma-separated), plus
`ANTHROPIC_API_KEY` / `OPENAI_API_KEY` for those providers. See `AgentConfig.from_env` in
`local_browser_agent/config.py` for the full list.

Run it without cloning anything, via uvx:

```bash
uvx --from "local-browser-agent[mcp] @ git+https://github.com/rogerflores3113/search" lba mcp
```

Claude Code:

```bash
claude mcp add local-browser-agent -e LBA_PROVIDER=anthropic -e ANTHROPIC_API_KEY=sk-ant-... -- \
  uvx --from "local-browser-agent[mcp] @ git+https://github.com/rogerflores3113/search" lba mcp
# or, from a checkout:
claude mcp add local-browser-agent -e LBA_PROVIDER=anthropic -e ANTHROPIC_API_KEY=sk-ant-... -- \
  uv run --directory /path/to/search lba mcp
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

## Upgrading from the `agent` package

The web app used to ship as a second top-level package, `agent`. It now lives inside the library package: old `agent.*` imports are `local_browser_agent.app.*` (for example `agent.main` is now `local_browser_agent.app.main`). Launch it with `python -m local_browser_agent.app` (or the `lba-app` console script). `import local_browser_agent` never imports the app. The distribution name (`local-browser-agent`) and user data locations are unchanged.

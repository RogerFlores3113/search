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
`AgentConfig.from_env()` builds a config from the `LBA_*` variables below (`ANTHROPIC_API_KEY` /
`OPENAI_API_KEY` are used when the provider matches and `LBA_API_KEY` is unset). See `examples/use_as_library.py`.

## Configuration

Configs are pydantic models and are validated when constructed: `ModelConfig` raises `ValueError`
(a pydantic `ValidationError`) for an unknown provider, `openai_compatible` without `base_url`, or a
`base_url` that is not an `http(s)` URL. `api_key` is not required at construction (it may come from the
environment); a missing key is reported by `check_provider` / `build_llm` and names the variables, e.g.
"Anthropic API key is not set. Set ANTHROPIC_API_KEY or LBA_API_KEY." `AgentConfig` requires
`1 <= max_steps <= 500` and `timeout_s > 0`. `from_env` errors name the variable and expected type
(`LBA_MAX_STEPS must be an integer, got 'abc'`).

| variable | type | default | meaning |
|---|---|---|---|
| `LBA_PROVIDER` | str | `ollama` | provider name |
| `LBA_MODEL` | str | provider default | model name |
| `LBA_API_KEY` | str | unset | API key (falls back to `ANTHROPIC_API_KEY` / `OPENAI_API_KEY`) |
| `LBA_BASE_URL` | http(s) URL | unset | endpoint override; required for `openai_compatible` |
| `LBA_TEMPERATURE` | float | unset | sampling temperature |
| `LBA_HEADLESS` | bool | `false` | run the browser without a window |
| `LBA_KEEP_ALIVE` | bool | `false` | leave a launched browser open after the run |
| `LBA_CHANNEL` | str | `chrome` | installed browser channel |
| `LBA_EXECUTABLE_PATH` | str | unset | browser binary path |
| `LBA_CDP_URL` | str | unset | attach to a running browser |
| `LBA_USER_DATA_DIR` | str | unset | Chrome profile directory |
| `LBA_MAX_STEPS` | int (1-500) | `25` | maximum agent steps |
| `LBA_TIMEOUT_S` | float (> 0) | `600` | run timeout in seconds |
| `LBA_USE_VISION` | bool | `true` | send screenshots to the model |
| `LBA_USE_JUDGE` | bool | `false` | grade the result with the judge |
| `LBA_ALLOWED_DOMAINS` | comma list | unset | restrict navigation to these domains |
| `LBA_BLOCKED_DOMAINS` | comma list | unset | extra blocked domains (added to `SAFETY_DEFAULTS`) |
| `LBA_ALLOW_EVALUATE` | bool | `false` | let the agent run page JavaScript without approval (off by default because scripts can submit forms) |
| `LBA_ALLOW_TELEMETRY` | `1` | unset | read at import; `1` lets an inherited `ANONYMIZED_TELEMETRY=true` stand |

Booleans accept `1/0`, `true/false`, `yes/no`, `on/off`. By default importing the package forces
`ANONYMIZED_TELEMETRY=false` (even if inherited as `true`) and sets `LITELLM_LOCAL_MODEL_COST_MAP=True`
so litellm does not fetch its cost map from GitHub. `local_browser_agent.__version__` reports the installed
version, and the package ships `py.typed`.

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
optional pre-flight check (raises `PreFlightError`). For `ollama` it lists local models; for `anthropic` and
`openai` it makes a small live API call (list models) to validate the key, so it needs network access and
the key must be valid; other providers are not checked. A custom provider without a model reports its own
name as the model name.

## Browser options

`BrowserConfig(headless=False, channel="chrome", executable_path=None, cdp_url=None, user_data_dir=None,
window_width=1280, window_height=800, llm_screenshot_width=1024, llm_screenshot_height=640, keep_alive=False)`

- **Attach to a running browser:** start Chrome with `--remote-debugging-port=9222` and set
  `BrowserConfig(cdp_url="http://127.0.0.1:9222")`. The agent attaches and does not kill your browser at the end.
- `keep_alive=True` also leaves a launched browser open after the run.
- `user_data_dir` reuses a Chrome profile (logins). Use a dedicated directory.

## Safety policy

`SafetyPolicy(blocked_domains, allowed_domains=None, guardrail_prompt=GUARDRAIL_PROMPT, gate_commerce_clicks=True, commerce_patterns=[...])`

- `blocked_domains` always includes `SAFETY_DEFAULTS` (banks, payments, government, medical, password managers); extra entries are added, none can be removed (also via `model_copy(update=...)`). Entries are lowercased with trailing dots stripped.
- `allowed_domains` restricts navigation to those domains. Blocked domains win: an allowed domain equal to or under a blocked one is dropped, and a list that is left empty raises `ValueError`.
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
configuration error (invalid flags such as `--max-steps 0`, `--timeout -1`, a malformed `--cdp-url`, an unwritable
`--trace` path, invalid `LBA_*` values, or `lba eval` unavailable); `130` interrupted (Ctrl-C). Flag overrides go
through the same validation as `AgentConfig`, and error messages are one `field: message` line per problem.

**Output streams:** with `--json`, stdout is always one JSON document shaped like `RunResult`, including when
pre-flight fails (then `status` is `"error"`, `success` is `null`, `errors` holds the message, `steps` is empty);
the human-readable message goes to stderr. Without `--json`, stdout holds the human summary (status, steps, result,
blocked actions) and the failure messages go to stderr. Logs always go to stderr. `-q` and `--json` mean errors only
from this library and nothing at all from browser-use (no emoji, no tracebacks); `--log-level` overrides that and
applies to everything. The default is `info` (`warning` for `mcp`). ANSI colour is stripped when stderr is not a
terminal. The library itself configures no logging on import; only the CLI and MCP entry points do.

**Pre-flight:** unless `--no-preflight`, `lba run` checks the provider first. For `ollama` it queries the local
server; for `anthropic` and `openai` it makes a **live API call** (listing models) with your key, so it needs
network access and can fail on a bad key or an outage. Chrome-not-found is also reported as a pre-flight error.

**Trace (`--trace PATH`):** `JsonlTraceSink` *appends* to an existing file (it never truncates), one JSON object
per event. Each record has `ts` (ISO 8601, UTC) and `run_id` (a uuid4 per sink, i.e. per CLI invocation), so
several runs can share a file. A pre-flight failure still writes `error_msg`, `state: error` and `done` events, with
the same `run_id` as the `--json` output. The path is checked up front: if it cannot be written the CLI exits 2.

## MCP server

Tools: `run_browser_task(task, start_url?, max_steps?, allowed_domains?)` and `get_agent_config()` (no secrets;
API key shown as `set`, URL credentials/tokens and `model.extra` values redacted). Both declare an `outputSchema`, so
clients receive `structuredContent`. The server sends `instructions` on `initialize` (what the tools do, one task at
a time, the safety gates, the key `LBA_*` variables).

- Configuration comes from the `LBA_*` environment variables in the [Configuration table](#configuration)
  (plus `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` for those providers). It is validated once at startup: a bad value
  prints a clear message to stderr and `lba mcp` exits with code 2 instead of failing every call.
- One task at a time; a concurrent call fails at once with a `busy` error.
- `max_steps` must be 1-200; `allowed_domains`, if given, must be non-empty; `start_url`, if given, must be an
  `http(s)` URL with a host.
- If the server has `LBA_ALLOWED_DOMAINS`, a call's `allowed_domains` can only **narrow** it, using browser-use's
  matching: `*.a.com` covers `a.com` and every subdomain, a plain `a.com` covers only `a.com` (and `www.a.com`). So
  with server `*.a.com` a call may ask for `a.com`, `x.a.com` or `*.x.a.com`, but with a plain server `a.com` a call
  entry `*.a.com` or `x.a.com` is dropped. If nothing survives, an error is returned and nothing runs. Without a
  server allowlist the call's list is used. Blocked domains (banks, payments, ...) always stay blocked.
- **One error shape.** Every failure, including schema violations (`max_steps=0`, `allowed_domains=[]`), rejected
  arguments, a busy server and bad `LBA_*` values, is returned with `isError: true` and a complete `RunResult`-shaped
  object in `structuredContent` (and as JSON in the text content): `status: "error"`, `success: null`, `errors`,
  and an `error_kind` of `invalid_argument`, `busy`, `config` or `internal`. Failed real runs return their own
  `RunResult` (any status other than `success` is `isError: true`).

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

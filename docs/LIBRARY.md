# Using local-browser-agent as a library

`local_browser_agent` is the agent loop (browser-use + your Chrome) as an importable package, with a
CLI (`lba`) and an MCP server. Importing it reads no config, touches no disk and uses no network
(it forces `ANONYMIZED_TELEMETRY=false`, `BROWSER_USE_CLOUD_SYNC=false` and `LITELLM_LOCAL_MODEL_COST_MAP=True`,
and installs no logging handlers; see [Logging](#logging)).

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

Checking the outcome, streaming events and approving gated actions:

```python
import asyncio
from local_browser_agent import ActionRequest, AgentConfig, run_task

async def sink(event):  # any async callable; add `sink.wants_screenshots = False` to skip screenshots
    if event.type == "progress":
        print(f"step {event.step}/{event.max_steps}")

async def approval(req: ActionRequest) -> bool:  # asked before a purchase-like click; no callback = deny
    return input(f"Allow {req.action_name} on {req.url} ({req.element_label})? [y/N] ").lower() == "y"

result = asyncio.run(run_task("Add a USB-C cable to the cart", AgentConfig.from_env(),
                              sinks=[sink], approval=approval, sink_timeout_s=10))
if result.status == "success":
    print(result.final_result)
else:  # run failures never raise; they come back here
    print(result.status, result.error_kind, result.errors)  # e.g. error chrome_missing / cdp_connect / timeout
```

`run_task_sync(...)` is the same call wrapped in `asyncio.run`. For control (pause/resume/stop), use
`BrowserAgent(config, sinks=..., approval=...)` and `await agent.run(task, start_url=None)`.
`AgentConfig.from_env()` builds a config from the `LBA_*` variables below (`ANTHROPIC_API_KEY` /
`OPENAI_API_KEY` are used when the provider matches and `LBA_API_KEY` is unset). See `examples/use_as_library.py`.

### Recommended embedding setup

```python
import asyncio
from local_browser_agent import AgentConfig, configure_logging, run_task

configure_logging("warning")  # one plain stderr handler; no browser-use emoji/traceback noise

async def fetch(task: str) -> str | None:
    try:
        config = AgentConfig.from_env()
    except ValueError as exc:
        # One line per bad LBA_* variable; see the Errors table below.
        raise RuntimeError(f"invalid LBA_* configuration:\n{exc}") from exc
    try:
        result = await run_task(task, config, sink_timeout_s=10)
    except asyncio.CancelledError:
        # Your own cancellation (timeout, shutdown): the browser is torn down before this propagates.
        # Clean up your side and re-raise.
        raise
    match result.error_kind:
        case None if result.status == "success":
            return result.final_result
        case "chrome_missing" | "cdp_connect" | "preflight" | "config":
            raise RuntimeError(f"setup problem: {result.errors}")  # fix the environment, retrying will not help
        case "captcha" | "start_url_blocked":
            return None  # needs a human / a different URL
        case "timeout" | "stopped":
            return None
        case _:  # "agent_error", or a failed run without an error_kind
            print(result.status, result.errors)
            return None
```

Without `configure_logging`, a failed run still logs one short `WARNING run <id> failed (<error_kind>)` line on the
`local_browser_agent` logger (the full text is in `result.errors`, and at DEBUG); browser-use's duplicate failure
records are dropped by filters on its loggers, whatever handlers your application uses, unless you set the
`browser_use` logger to INFO or DEBUG. Setting the *root* logger to INFO has the same effect and brings
browser-use's own records back; keep them quiet with `logging.getLogger("browser_use").setLevel(logging.WARNING)`.

## Configuration

Configs are pydantic models and are validated when constructed: `ModelConfig` raises `ValueError`
(a pydantic `ValidationError`) for an unknown provider, `openai_compatible` without `base_url`, or a
`base_url` that is not an `http(s)` URL. `api_key` is not required at construction (it may come from the
environment); a missing key is reported by `check_provider` / `build_llm` and names the variables, e.g.
"Anthropic API key is not set. Set ANTHROPIC_API_KEY or LBA_API_KEY." `AgentConfig` requires
`1 <= max_steps <= 500` and `timeout_s > 0`. `from_env` errors name the variable and expected type
(`LBA_MAX_STEPS must be an integer, got 'abc'`); all bad variables are reported together, one per line of the `ValueError` message.

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
| `LBA_ALLOW_LOCAL_NETWORK` | bool | `false` | let the browser reach localhost, private and link-local addresses (see Safety policy) |
| `LBA_APPROVAL_TIMEOUT_S` | float (>= 0) | `120` | seconds to wait for an approval before the gated action is denied; `0` waits forever |
| `LBA_ALLOW_TELEMETRY` | `1` | unset | read at import; `1` stops the import from forcing telemetry / cloud-sync / cost-map settings off |

Booleans accept `1/0`, `true/false`, `yes/no`, `on/off`. By default importing the package forces
`ANONYMIZED_TELEMETRY=false`, `BROWSER_USE_CLOUD_SYNC=false` (both even if inherited as `true`) and
`LITELLM_LOCAL_MODEL_COST_MAP=True` so litellm does not fetch its cost map from GitHub.

**Config objects** validate on assignment (`cfg.max_steps = -5` raises `ValidationError`). `repr()`/`str()` and
validation errors redact `base_url` / `cdp_url` userinfo and query strings and mask `ModelConfig.extra` values.
`model_dump()` / `model_dump_json()` return the **real secret values** (they are for persistence); use
`cfg.safe_dump()` (on `AgentConfig`, `ModelConfig`, `BrowserConfig`) for logs and display. Note that pydantic's
`ValidationError.errors()` still carries the raw `input`; do not log it verbatim. `local_browser_agent.__version__` reports the installed
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
window_width=1280, window_height=800, llm_screenshot_width=1024, llm_screenshot_height=640, keep_alive=False, allow_downloads=False)`

- **Attach to a running browser:** start Chrome with `--remote-debugging-port=9222` and set
  `BrowserConfig(cdp_url="http://127.0.0.1:9222")`. The agent attaches and does not kill your browser at the end.
- `cdp_url` must be an `http(s)` or `ws(s)` URL with a host.
- `keep_alive=True` also leaves a launched browser open after the run.
- `user_data_dir` reuses a Chrome profile (logins). Use a dedicated directory.
- The browser is launched with no extra permissions (no clipboard read/write, no notifications) and with downloads
  and PDF auto-download off. `allow_downloads=True` turns downloads back on.
- `LBA_ALLOW_TELEMETRY=1` only takes effect if `local_browser_agent` is imported before `browser_use` (the package
  sets the telemetry env vars at import time); otherwise set `ANONYMIZED_TELEMETRY` / `BROWSER_USE_CLOUD_SYNC` yourself.

## Safety policy

`SafetyPolicy(blocked_domains, allowed_domains=None, guardrail_prompt=GUARDRAIL_PROMPT, gate_commerce_clicks=True, commerce_patterns=[...], allow_evaluate=False, allow_local_network=False, approval_timeout_s=120.0)`

- **`allow_local_network=False` (default)** keeps the agent's browser off your machine and LAN. The block covers
  IP literals (every IP-address URL, public ones such as `http://8.8.8.8/` included: use a hostname, or set
  `allow_local_network=True` / `LBA_ALLOW_LOCAL_NETWORK=1`), `localhost`, the local suffixes `*.localhost`, `*.local`,
  `*.internal`, `*.lan`, `*.home.arpa`, `*.localdomain`, `*.intranet`, and single-label names such as `intranet` or
  `printer`. Suffixes are blocked in the browser profile (so link clicks and redirects are covered) and in the
  navigation tool. **Not caught:** DNS names that resolve to loopback or private addresses (`localtest.me`, `*.nip.io`,
  `*.sslip.io`, ...), because no DNS lookups are done. Use `allowed_domains` when you need strict isolation. A local `start_url` or `allowed_domains`
  entry is rejected unless you set `allow_local_network=True` (`LBA_ALLOW_LOCAL_NETWORK=1`), which is meant for
  local test fixtures and dev servers (the eval suite turns it on for its fixture server).
- **`approval_timeout_s=120.0`** is how long a gated action waits for the approval callback; on timeout it is denied.
  `None` or `0` waits forever; negative values are rejected. A `TimeoutError` raised by the callback itself is reported as
  "approval callback failed", not as a timeout.
- **Non-web schemes:** `chrome://`, `chrome-extension://`, `devtools://` and similar are blocked at the browser layer,
  and `file:` / `view-source:` are rejected by browser-use (no hostname). browser-use always allows `data:` and `blob:`
  URLs; those are only stopped by the tool-layer navigation gate, not by the browser profile.
- **`start_url`** must be `http(s)`, not blocked, inside `allowed_domains` (when set) and not local (unless allowed);
  otherwise the run returns `status="error"`, `error_kind="start_url_blocked"` before anything is launched.

- `blocked_domains` always includes `SAFETY_DEFAULTS`: about 90 domains covering banks, brokerages, crypto exchanges, payment apps (PayPal and its country sites, Venmo, Cash App, Wise, Zelle), identity providers and account settings (`accounts.google.com`, `myaccount.google.com`, `appleid.apple.com`, `login.microsoftonline.com`, `login.live.com`, `account.microsoft.com`), the AWS console and sign-in, tax sites, government, medical and password managers. Extra entries are added, none can be removed (also via `model_copy(update=...)`). Entries are normalised: scheme, userinfo, port, path and a leading `*.` are stripped and the host is canonicalised (so `https://evil.com:8080/x` and `*.evil.com` both mean `evil.com`, and `bücher.de` means `xn--bcher-kva.de`); an entry with no usable host raises `ValueError`. `github.com` stays reachable; its settings pages are path-level and not blocked. For a logged-in everyday Chrome profile, prefer an `allowed_domains` list for the sites the task needs.
- **Host canonicalisation:** before any domain, IP or local-network check a host is canonicalised like Chrome does
  (percent-decoding, NFKC, zero-width/format characters removed, `。` `．` `｡` read as dots, lowercase, trailing dot
  removed, IDNA/punycode). A host that cannot be canonicalised is denied.
- **Link targets:** a click on a link or form button whose `href` / `formaction` / form `action` points at a blocked
  domain, a local address or a browser-internal scheme (`chrome:`, `file:`, `view-source:`, ...) is denied like a
  `navigate` action. Relative links, `javascript:`, `mailto:` and `tel:` are not treated as navigations.
- **Enter / Space** on a focused control are checked against the live focused element; when it cannot be read they
  are gated unless the last known focus was a text field.
- `allowed_domains` restricts navigation to those domains. Public suffixes such as `*.co.uk` or `com.au` are rejected;
  name a specific site (`*.example.co.uk`). Shared-hosting suffixes such as `github.io`, `herokuapp.com`, `vercel.app` or `pages.dev` are rejected the same way. Blocked domains win: an allowed entry that is equal to, under, or a wildcard covering a blocked domain is dropped with a warning naming it (for example `*.google.com` covers `accounts.google.com`, so allow `google.com` and `www.google.com` instead), and a list that is left empty raises `ValueError`.
- The guardrail prompt is appended to the system prompt.
- **Commerce gate:** click actions whose target label matches a commerce pattern ("Buy now", "Checkout", "Place order", "Pay", ...) are blocked in the tool layer, independent of the model. If you pass `approval=async (ActionRequest) -> bool`, it is asked first (`ActionRequest` has `action_name, params, element_label, url`); returning `True` lets the click through. Without a callback the click is blocked, the agent gets an error, and the attempt is listed in `RunResult.blocked_actions`.
- The element label is read from the accessibility name / aria-label / text of the clicked element via `browser_session.get_element_by_index`, and the classification also covers its nearest interactive ancestors (up to 16 levels: label text, aria-label, title, value, `href`, `formaction`, form `action`), so a click on a `<span>` inside a "Place order" button or a `/checkout` link is gated like a click on the button itself. Labels are matched case-insensitively with spacing, zero-width characters and common lookalike letters removed ("BuY NoW", "buynow", "ʙᴜʏ" all count). Coordinate clicks and unlabeled elements cannot be gated.
- `upload_file` always asks the approval callback (it sends a local file to a site), and `select_dropdown` is gated when the chosen option reads as a purchase. "Add to cart" is not gated.
- **Irreversible actions:** with commerce gating on, a verb (delete, close, deactivate, terminate, remove, cancel, end, erase) followed by an object (account, profile, data, subscription, membership, plan, auto-renewal, consent) is gated, with optional words like "your", "this" or "all" in between: "Cancel your subscription", "Delete this account", "Delete all data", "Withdraw consent", a bare "Deactivate". So are "Transfer money", "Wire transfer" and "Sell all". The same check runs when Enter or Space activates a focused button and when a dropdown option is chosen. Info labels ("How to delete your account", "... policy", "... history") are not gated. Generic buttons (Confirm, Continue, Submit, Next, Done...) are gated only on checkout flows: cart, basket, bag or checkout paths, `review` beside one of those, `order`/`orders` followed by new, confirm, review or pay, and pay, payment or billing as the first path segment or under checkout, cart, account or order. Content pages such as `/arts/review/film.html` or `/orders?page=2` are not. Allow, Accept, Post, Publish, Send message, a bare Delete and a bare Cancel are not gated. The callback gets `ActionRequest.kind`: `"commerce"` or `"irreversible"`.
- **Strict preset:** `SafetyPolicy.strict(allowed_domains=["example.com"])` is the preset for profiles logged in to real accounts. It requires a non-empty allow-list (`ValueError` otherwise) and keeps commerce gating on, so purchases and irreversible actions go to your approval callback and are denied without one. The default blocklist cannot be removed; everyday sites such as icloud.com, dropbox.com and mail.google.com are deliberately not in it, so use an allow-list for those.

## Sinks and tracing

A sink is any `async def sink(event)`. Events: `StateEvent, ModelInfoEvent, ThoughtEvent, ActionDetailEvent, ProgressEvent, TokenEvent, ScreenshotEvent, SummaryEvent, ErrorEvent, DoneEvent, HumanNeededEvent, StepCompletedEvent`. A failing sink never crashes a run: the first failure of each sink is logged with a traceback, later ones as a one-line warning (naming the event type and the sink's running failure count), so a broken sink cannot flood the log. A sink that times out (5s) three times in a row is dropped for the rest of the run, with one warning. Both numbers are configurable per run: `run_task(..., sink_timeout_s=10, sink_max_timeouts=5)` (also `run_task_sync` and `BrowserAgent(...)`); the module defaults are `runner.SINK_TIMEOUT_S` and `runner.SINK_MAX_TIMEOUTS`.

- `QueueSink(data_q, control_q=None)`: lossy `put_nowait` for data events; lifecycle events (state, model_info, summary, error_msg, done) block up to 2s.
- `JsonlTraceSink(path, include_screenshots=False)`: one JSON line per event, appended to the file (an existing file is not truncated); each record has `ts` (UTC ISO 8601) and `run_id`: the run's id (the same as `RunResult.run_id`, stamped on every event by `BrowserAgent`), or the sink's own uuid4 for events emitted outside a run.
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

`run_id, task, status ("success"|"failed"|"error"|"timeout"|"stopped"), success (bool|None), final_result, steps (list of StepRecord: index, action_type, target_label, value, url, error, duration_ms), step_count, duration_s, cost_usd (None for Ollama), errors, urls_visited, blocked_actions, error_kind`; `.to_dict()` gives plain JSON-able data.

`error_kind` says why a run ended badly (`None` for success or a plain agent "failed"):

| `error_kind` | meaning |
|---|---|
| `chrome_missing` | no Chrome/Chromium found (`ChromeNotFoundError`) |
| `preflight` | provider / API key / model check failed (`PreFlightError` or your `preflight=` callable) |
| `config` | invalid configuration found while building the LLM or browser |
| `cdp_connect` | could not attach to Chrome at `BrowserConfig.cdp_url` |
| `timeout` | `timeout_s` elapsed (`status="timeout"`) |
| `captcha` | CAPTCHA / human check stopped the run (`on_captcha="fail"`) |
| `stopped` | `stop()` was called (`status="stopped"`) |
| `start_url_blocked` | `start_url` not http(s), blocked, outside `allowed_domains` or local |
| `agent_error` | any other error during the run |
| `invalid_argument` | MCP only: a tool argument was rejected before the run started |
| `busy` | MCP only: another task is already running on this server |
| `internal` | MCP only: unexpected server error outside the run |

`ChromeNotFoundError` and `PreFlightError` are exported from `local_browser_agent`.

### Errors: exceptions vs results

`BrowserAgent.run()`, `run_task()` and `run_task_sync()` report **run failures as a result, not an exception**: you
get a `RunResult` with `status="error"` (or `"timeout"` / `"stopped"` / `"failed"`), the messages in `errors`
and a machine-readable `error_kind`: `chrome_missing`, `preflight`, `config` (invalid configuration found while
building the LLM or browser), `cdp_connect`, `start_url_blocked`, `timeout`, `stopped`, `captcha` or `agent_error`
(see the table above). Check `result.status` / `result.error_kind` rather than wrapping the call in `try`.

What **does raise**:

| exception | when |
|---|---|
| `RuntimeError` | `run()` called while the same `BrowserAgent` is already running (use one instance per concurrent run); `run_task_sync()` called from inside a running event loop (use `await run_task(...)`) |
| `pydantic.ValidationError` (a `ValueError`) | constructing or assigning a config object with invalid values (`ModelConfig`, `BrowserConfig`, `SafetyPolicy`, `AgentConfig`), e.g. `cfg.max_steps = -5` |
| `ValueError` | `sink_timeout_s` that is not a finite number > 0, or `sink_max_timeouts` that is not an integer >= 1 (`BrowserAgent(...)`, `run_task`, `run_task_sync`; raised before anything runs); `AgentConfig.from_env()` on a bad `LBA_*` value (the message names the variable and expected type); `register_provider` / `build_llm` for an unknown provider |

`KeyboardInterrupt` and `asyncio.CancelledError` propagate as usual.

**Reuse and stopping.** A `BrowserAgent` can be reused for sequential runs but not run concurrently: a second
`run()` while one is in flight raises `RuntimeError` (use one instance per concurrent run). `stop()` lets the current
step finish for about 2 seconds, then cancels the in-flight action (model call, browser action or a pending
approval callback), so a stopped run ends within a few seconds with `status="stopped"`.

## Logging

Importing `local_browser_agent` (and browser-use through it) installs **no handlers on the root logger** and does not touch the logger class (`logging.Logger.manager.loggerClass`); the quiet-log filters for browser-use's failure noise are installed only while a run is in flight (reference counted, fully restored afterwards) or, for the `lba` CLI and MCP server, for the process lifetime (the package logger only gets a `NullHandler`, per stdlib etiquette): the
package sets `BROWSER_USE_SETUP_LOGGING=false` before importing browser-use unless you already set it. Library
logs go to the `local_browser_agent` logger (and `browser_use`), so configure them with the standard `logging`
module; unconfigured, Python shows only warnings and errors on stderr. Set `BROWSER_USE_SETUP_LOGGING=true`
before the import to get browser-use's own stderr handler back. `lba` configures logging itself (`--log-level`, `-q`).

To get the same tidy output in your own program, call `local_browser_agent.configure_logging(level="warning",
*, color=None, third_party=None)` once at startup (it is exported from the package and never called on import).
`level` applies to the `local_browser_agent` logger; `third_party` sets the level for browser-use and its event bus
(`"debug"`, `"info"`, `"warning"`, `"error"`, `"off"`, or `None` for the same as `level`). It replaces browser-use's
emoji/traceback-laden console handler with one plain stderr handler, strips ANSI colour when stderr is not a
terminal, and (at every level except `debug`) drops browser-use's misleading "Optimizing domain list ... pattern
matching is not supported for lists >= 100" warning, since wildcard `allowed_domains` entries are handled by this
package. At warning level and above it also drops browser-use's duplicate multi-line ERROR records about a failed
browser start ("Root CDP client not initialized", ...); the failure is in `RunResult.errors` / `error_kind`. They
are kept at `info` / `debug`. It is safe to call repeatedly.

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

**Exit codes** (also in `lba run --help`):

| code | meaning |
|---|---|
| `0` | success |
| `1` | the run failed, errored, timed out or was stopped, including a `--start-url` the safety policy blocks (blocked domain, outside `--allowed-domain`, local address: `error_kind` `start_url_blocked`, found at run time) |
| `2` | usage or configuration error: invalid flags (`--max-steps 0`, `--timeout -1`), a malformed `--cdp-url` or `--start-url` (not an `http(s)` URL with a host), an unwritable `--trace` path, invalid `LBA_*` values; also `lba eval` unavailable |
| `3` | environment not ready: Chrome not found, provider pre-flight failed or the CDP endpoint is unreachable (`error_kind` `chrome_missing`, `preflight`, `cdp_connect`) |
| `130` | interrupted (Ctrl-C) |

Flag overrides go through the same validation as `AgentConfig`, with one `field: message` line per problem. Errors
are prefixed `lba run: error: ...` (`lba mcp: error: ...` for the MCP server). With `--json`, a configuration
error has `error_kind: "config"` and `errors` is a list with one entry per problem.

**Output streams:** with `--json`, stdout is always one JSON document shaped like `RunResult`, including when
pre-flight fails (then `status` is `"error"`, `success` is `null`, `errors` holds the message, `steps` is empty);
the human-readable message goes to stderr. Without `--json`, stdout holds the human summary (status, steps, result,
blocked actions) and the failure messages go to stderr. Logs always go to stderr. `-q` and `--json` mean errors only
from this library and nothing at all from browser-use (no emoji, no tracebacks); `--log-level` overrides that and
applies to everything. The default is `info` (`warning` for `mcp`). ANSI colour is stripped when stderr is not a
terminal. The library itself configures no logging on import; only the CLI and MCP entry points do.

**Pre-flight:** unless `--no-preflight`, `lba run` checks the provider first. For `ollama` it queries the local
server; for `anthropic` and `openai` it makes a **live API call** (listing models) with your key, so it needs
network access and can fail on a bad key or an outage. A failed pre-flight exits with code 3; a missing Chrome is
reported by the run itself (`error_kind: "chrome_missing"`), also exit code 3.

**Trace (`--trace PATH`):** `JsonlTraceSink` *appends* to an existing file (it never truncates), one JSON object
per event. Each record has `ts` (ISO 8601, UTC) and `run_id` (a uuid4 per sink, i.e. per CLI invocation), so
several runs can share a file. A pre-flight failure still writes `error_msg`, `state: error` and `done` events, with
the same `run_id` as the `--json` output. The path is checked up front: if it cannot be written the CLI exits 2.
The parent directory is not created: a missing directory is an error (`cannot write --trace ...: directory does not
exist`, exit 2).

## MCP server

Tools: `run_browser_task(task, start_url?, max_steps?, allowed_domains?)` and `get_agent_config()` (no secrets;
API key shown as `set`, URL credentials/tokens and `model.extra` values redacted). Both declare an `outputSchema`, so
clients receive `structuredContent` (`get_agent_config`'s schema types the `model`, `browser` and `safety` sections). The server sends `instructions` on `initialize` (what the tools do, one task at
a time, the safety gates, the key `LBA_*` variables).

- Configuration comes from the `LBA_*` environment variables in the [Configuration table](#configuration)
  (plus `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` for those providers). It is validated once at startup: a bad value
  prints one line per problem to stderr (see degraded mode below).
- **Degraded mode.** With an invalid configuration the server still starts and completes the MCP handshake, so the
  client lists both tools instead of showing only "Connection closed". `run_browser_task` then returns a
  `RunResult`-shaped error (`error_kind: "config"`, one `errors` entry per problem, each
  `invalid configuration: <field>: <message>`) and `get_agent_config` returns `{status: "error", error_kind: "config",
  error, errors}`. The same lines are printed to stderr at startup. Pass `lba mcp --strict`, set `LBA_MCP_STRICT=1` or call
  `serve(strict=True)` to get the old behaviour: print the problems and exit with code 2 before the handshake.
  Claude Desktop shows an MCP server's stderr in Claude Desktop's MCP log (the per-server log file for
  `local-browser-agent`, reachable from its Developer settings / log folder), which is where those startup lines appear.
- One task at a time; a concurrent call fails at once with a `busy` error.
- **Progress.** When the client sends a `progressToken`, `run_browser_task` emits an MCP progress notification
  per agent step (`progress` = step, `total` = max steps, `message` = e.g. `Step 3/25: click: Sign in`).
  Every `http(s)` URL in that text has its credentials and query-string values masked (the host and path are kept:
  path segments are not redacted, so do not put secrets in paths). Clients without a token are unaffected. Both tools advertise `additionalProperties: false` in their `inputSchema`.
  An unusable `allowed_domains` entry such as `*.com` is `invalid_argument`; an unreachable `LBA_CDP_URL` is `cdp_connect`.
- `max_steps` must be 1-200; `allowed_domains`, if given, must be non-empty; `start_url`, if given, must be an
  `http(s)` URL with a host. Unknown arguments are rejected with `invalid_argument` naming the key(s). All of this
  validation (and loading the `LBA_*` config) happens before the busy check, so an invalid call is reported as
  `invalid_argument` / `config` even while another task is running.
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

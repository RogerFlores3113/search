# Search as a computer-use framework: plan

Audited: `main` at `8572a88` (2026-05-19). Living version of this plan, with the
tickable checklist: "Search: Framework Plan" Claude Doc.

## Summary

The agent loop works, but it is welded to the web UI: `local_browser_agent/app/runner.py::run_agent`
reads a global config singleton, writes back into `local_browser_agent.app.main` module globals,
always writes `history.db` / `runs.jsonl` / stdout, and returns `None`. Other
projects cannot import it. The plan adds a library package, `local_browser_agent`,
that owns the loop; the web app, a CLI, an MCP server and an eval suite sit on top.

## Findings (worst first)

| # | Finding | Where |
|---|---------|-------|
| 1 | Loop reads module-level `config` singleton; two callers cannot use different settings | `local_browser_agent/app/runner.py`, `local_browser_agent/app/config.py` |
| 2 | `run_agent` imports `local_browser_agent.app.main` and writes `_active_agent` / queues into it | `local_browser_agent/app/runner.py` |
| 3 | Every run writes `history.db`, `runs.jsonl` and `print()`; paths fixed at import | `runner.py`, `db.py`, `paths.py` |
| 4 | `run_agent` returns `None`; no result object (success, answer, steps, cost) | `local_browser_agent/app/runner.py` |
| 5 | browser-use telemetry on by default; cloud sync follows it | browser-use `config.py` (fixed in step 1) |
| 6 | Safety is prompt text + `prohibited_domains`; no enforced action gate | `GUARDRAIL_PROMPT` |
| 7 | Providers hard-coded to three | `build_llm` |
| 8 | Always a fresh headed Chrome; no headless, no CDP attach, no profile dir | `BrowserProfile(...)` |
| 9 | CAPTCHA pause has no resume; `use_judge=True` default adds an LLM call per run | `log_step`, browser-use `Agent` |
| 10 | Import name `agent` is generic and collides in other projects | `pyproject.toml` |

## Target API (contract for step 2)

New top-level package `local_browser_agent/` (same distribution, `local-browser-agent`).
Importing it must not read env, touch disk, or import `agent` (the web app).

```python
from local_browser_agent import (
    AgentConfig, ModelConfig, BrowserConfig, SafetyPolicy,
    BrowserAgent, RunResult, StepRecord, run_task, run_task_sync,
    register_provider, build_llm,
)
```

- `ModelConfig(provider="ollama", model=None, api_key: SecretStr|None, base_url=None, temperature=None, extra: dict = {})`.
  Default models per provider: ollama `qwen2.5vl:7b`, anthropic `claude-sonnet-4-5`, openai `gpt-4o`.
- `BrowserConfig(headless=False, channel="chrome", executable_path=None, cdp_url=None, user_data_dir=None, window_width=1280, window_height=800, llm_screenshot_width=1024, llm_screenshot_height=640, keep_alive=False)`.
- `SafetyPolicy(blocked_domains=SAFETY_DEFAULTS, allowed_domains=None, guardrail_prompt=GUARDRAIL_PROMPT, gate_commerce_clicks=True, commerce_patterns=[...])`.
  `blocked_domains` always unions `SAFETY_DEFAULTS` (cannot be shrunk).
- `AgentConfig(model, browser, safety, max_steps=25, timeout_s=600, use_vision=True, system_prompt_extension=None, use_judge=False, calculate_cost=True)`,
  `AgentConfig.from_env(prefix="LBA_")` for convenience only.
- `register_provider(name, factory: Callable[[ModelConfig], BaseChatModel])`; built-ins
  `ollama`, `anthropic`, `openai`, `openai_compatible` (needs `base_url`), `litellm` (any LiteLLM model string).
- `BrowserAgent(config, *, sinks=(), approval=None)`; `await agent.run(task, start_url=None) -> RunResult`;
  `pause()`, `resume()`, `stop()`. `approval` is `async (ActionRequest) -> bool`, asked before a gated click.
- `RunResult`: `run_id, task, status ("success"|"failed"|"error"|"timeout"|"stopped"), success: bool|None,
  final_result: str|None, steps: list[StepRecord], step_count, duration_s, cost_usd|None, errors: list[str],
  urls_visited: list[str], blocked_actions: list[str]`. `StepRecord`: `index, action_type, target_label, value, url, error, duration_ms`.
- Event sinks: async callables taking an event dataclass. Built-ins: `QueueSink(data_q, control_q)`
  (same lossy/lossless split as the app), `JsonlTraceSink(path, include_screenshots=False)`, `CallbackSink(fn)`.
- `run_task(task, config=None, **kw)` / `run_task_sync(...)` wrap `BrowserAgent`.
- Entry points: `lba run "task" [--provider --model --headless --cdp-url --max-steps --start-url --json --trace PATH]`,
  `lba mcp` (stdio MCP server; tool `run_browser_task(task, start_url?, max_steps?, allowed_domains?)`, one run at a time),
  `lba eval` (step 3).

## Change list

- P0 (step 2): telemetry off (done in step 1); library package and config objects; `BrowserAgent` / `RunResult`; event sinks.
- P1 (step 2): provider registry; browser backends; tool-level commerce gate; CLI + MCP server; docs and example.
- P2 (step 3): local fixture site; state-based checkers; `lba eval` runner with JSON/Markdown output; harness self-test in CI; real-model baseline.
- P3 (follow-up): ~~move the web app onto `BrowserAgent`~~ (done); rename the app package; ~~CAPTCHA resume~~ (done, `on_captcha="pause"`); eval in CI on a cheap model.

"""``lba`` command line: run | mcp | eval."""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import uuid
from collections.abc import Sequence

from local_browser_agent.log import LEVELS


def _version() -> str:
    try:
        from importlib.metadata import version

        return version("local-browser-agent")
    except Exception:
        from local_browser_agent import __version__

        return __version__


def _add_log_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("-q", "--quiet", action="store_true", help="only log errors to stderr")
    p.add_argument("--log-level", choices=LEVELS, help="stderr log level (default: info; warning with --json or for mcp)")


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="lba", description="Local browser agent: run a task, serve MCP, or run evals.")
    p.add_argument("--version", action="version", version=f"lba {_version()}")
    sub = p.add_subparsers(dest="command", required=True)

    r = sub.add_parser("run", help="run one natural-language browser task")
    r.add_argument("task", help="what the agent should do")
    r.add_argument("--provider", help="ollama | anthropic | openai | openai_compatible | litellm (default: $LBA_PROVIDER or ollama)")
    r.add_argument("--model", help="model name (default depends on provider)")
    r.add_argument("--base-url", help="API base URL / Ollama host")
    r.add_argument("--headless", action="store_true", default=None, help="run the browser headless")
    r.add_argument("--cdp-url", help="attach to a running browser via CDP instead of launching one")
    r.add_argument("--max-steps", type=int, help="maximum agent steps")
    r.add_argument("--timeout", type=float, help="overall timeout in seconds")
    r.add_argument("--start-url", help="navigate here before the agent starts")
    r.add_argument("--allowed-domain", action="append", dest="allowed_domains", help="restrict to this domain (repeatable)")
    r.add_argument("--json", action="store_true", help="print the RunResult as JSON")
    r.add_argument("--trace", metavar="PATH", help="append every event as a JSON line to PATH")
    r.add_argument("--no-preflight", action="store_true", help="skip the provider availability check")

    _add_log_args(r)

    m = sub.add_parser("mcp", help="start the stdio MCP server (config from LBA_* env vars)")
    _add_log_args(m)
    ev = sub.add_parser("eval", help="run the evaluation suite (remaining args are forwarded)", add_help=False)
    ev.add_argument("rest", nargs=argparse.REMAINDER)
    return p


def _config_from_args(args: argparse.Namespace):
    from local_browser_agent.config import AgentConfig, SafetyPolicy

    cfg = AgentConfig.from_env()
    if args.provider:
        cfg.model.provider = args.provider.lower()
        # re-resolve provider-specific key fallback when provider was overridden
        if cfg.model.api_key is None:
            import os

            key = os.environ.get(f"{cfg.model.provider.upper()}_API_KEY") if cfg.model.provider in ("anthropic", "openai") else None
            if key:
                from pydantic import SecretStr

                cfg.model.api_key = SecretStr(key)
    if args.model:
        cfg.model.model = args.model
    if args.base_url:
        cfg.model.base_url = args.base_url
    if args.headless:
        cfg.browser.headless = True
    if args.cdp_url:
        cfg.browser.cdp_url = args.cdp_url
    if args.max_steps:
        cfg.max_steps = args.max_steps
    if args.timeout:
        cfg.timeout_s = args.timeout
    if args.allowed_domains:
        cfg.safety = SafetyPolicy(**{**cfg.safety.model_dump(), "allowed_domains": args.allowed_domains})
    return cfg


def _human_summary(result) -> str:
    lines = [
        f"status:   {result.status}",
        f"steps:    {result.step_count}  ({result.duration_s:.1f}s)",
    ]
    if result.cost_usd is not None:
        lines.append(f"cost:     ${result.cost_usd:.4f}")
    if result.final_result:
        lines.append(f"result:   {result.final_result}")
    for b in result.blocked_actions:
        lines.append(f"blocked:  {b}")
    for e in result.errors:
        lines.append(f"error:    {e}")
    return "\n".join(lines)


def _log_level(args: argparse.Namespace, default: str) -> str:
    if args.log_level:
        return args.log_level
    return "error" if args.quiet else default


def _error_result(task: str, message: str, status: str = "error") -> dict:
    from local_browser_agent.runner import RunResult

    return RunResult(run_id=str(uuid.uuid4()), task=task, status=status, success=None, errors=[message]).to_dict()


def _fail(args: argparse.Namespace, message: str, code: int, *, status: str = "error", trace=None) -> int:
    """Report a failure that happened before/outside a run: text on stderr, JSON on stdout."""
    print(f"lba: {message}", file=sys.stderr)
    if getattr(args, "json", False):
        print(json.dumps(_error_result(args.task, message, status), indent=2))
    if trace is not None and trace.events_written == 0:
        from local_browser_agent.events import DoneEvent, ErrorEvent, StateEvent

        async def write():
            for ev in (ErrorEvent(message=message), StateEvent(state="error"), DoneEvent()):
                await trace(ev)

        try:
            asyncio.run(write())
        except Exception:
            pass
    return code


def _cmd_run(args: argparse.Namespace) -> int:
    from local_browser_agent.log import configure_logging

    configure_logging(_log_level(args, "warning" if args.json else "info"))
    from local_browser_agent import run_task
    from local_browser_agent.models import PreFlightError, check_provider
    from local_browser_agent.sinks import JsonlTraceSink

    try:
        cfg = _config_from_args(args)
    except Exception as e:
        return _fail(args, f"invalid configuration: {e}", 2)
    trace = JsonlTraceSink(args.trace) if args.trace else None
    sinks = [trace] if trace else []

    async def go():
        if not args.no_preflight:
            await check_provider(cfg.model)
        return await run_task(args.task, cfg, sinks=sinks, start_url=args.start_url)

    try:
        result = asyncio.run(go())
    except PreFlightError as e:
        return _fail(args, str(e), 1, trace=trace)
    except KeyboardInterrupt:
        return _fail(args, "interrupted", 130, status="stopped", trace=trace)
    print(json.dumps(result.to_dict(), indent=2) if args.json else _human_summary(result))
    return 0 if result.status == "success" else 1


def _cmd_eval(rest: Sequence[str]) -> int:
    try:
        from local_browser_agent.evals.cli import main as eval_main
    except ImportError as e:
        print(f"lba eval is not available in this install ({e}).", file=sys.stderr)
        return 2
    return int(eval_main([a for a in rest if a != "--"]) or 0)


def main(argv: Sequence[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    # Forward everything after `eval` untouched: argparse REMAINDER does not
    # capture leading options such as `--self-test`.
    if argv and argv[0] == "eval":
        return _cmd_eval(argv[1:])
    args = _build_parser().parse_args(argv)
    if args.command == "run":
        return _cmd_run(args)
    if args.command == "mcp":
        from local_browser_agent.mcp_server import serve

        serve(_log_level(args, "warning"))
        return 0
    if args.command == "eval":
        return _cmd_eval(args.rest or [])
    return 2


if __name__ == "__main__":
    sys.exit(main())

"""``lba`` command line: run | mcp | eval."""
from __future__ import annotations

import argparse
import asyncio
import errno
import json
import logging
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


EXIT_OK, EXIT_FAILED, EXIT_USAGE, EXIT_ENV, EXIT_INTERRUPTED = 0, 1, 2, 3, 130
# error_kind values meaning "the environment is not ready" (no browser / provider / CDP endpoint),
# as opposed to the task itself failing: `lba run` exits 3 for these.
ENV_ERROR_KINDS = frozenset({"chrome_missing", "preflight", "cdp_connect"})

RUN_EPILOG = """\
safety: IP-address URLs, localhost and local network names are blocked unless
LBA_ALLOW_LOCAL_NETWORK=1; use a hostname.

exit codes:
  0    success
  1    the run failed, timed out, was stopped or errored (including a start URL that
       the safety policy blocks: error_kind start_url_blocked)
  2    usage or configuration error (bad flags, malformed --cdp-url / --start-url,
       unwritable --trace path, invalid LBA_* values)
  3    environment not ready: Chrome not found, provider pre-flight failed or the
       CDP endpoint is unreachable (error_kind chrome_missing, preflight, cdp_connect)
  130  interrupted (Ctrl-C)
"""


def _add_log_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("-q", "--quiet", action="store_true", help="errors only on stderr; nothing from browser-use")
    p.add_argument("--log-level", choices=LEVELS, help="stderr log level (default: info; warning for mcp; errors only with --json)")


class _UsageError(Exception):
    """argparse rejected the command line (raised instead of exiting, so ``--json`` can still get its document)."""

    def __init__(self, parser: argparse.ArgumentParser, message: str) -> None:
        super().__init__(message)
        self.parser = parser
        self.message = message


class _Parser(argparse.ArgumentParser):
    def error(self, message: str):  # type: ignore[override]
        raise _UsageError(self, message)


def _wants_json(argv: Sequence[str]) -> bool:
    """Is ``--json`` (or an unambiguous argparse prefix such as ``--jso``) among the flags?"""
    for a in argv:
        if a == "--":
            return False
        if a.startswith("--") and len(a) >= 3:
            name = a.split("=", 1)[0]
            if len(name) >= 3 and "--json".startswith(name):
                return True
    return False


def _build_parser() -> argparse.ArgumentParser:
    p = _Parser(prog="lba", description="Local browser agent: run a task, serve MCP, or run evals.")
    p.add_argument("--version", action="version", version=f"lba {_version()}")
    sub = p.add_subparsers(dest="command", required=True)

    r = sub.add_parser(
        "run", prog="lba run", help="run one natural-language browser task",
        epilog=RUN_EPILOG, formatter_class=argparse.RawDescriptionHelpFormatter)
    r.add_argument("task", help="what the agent should do")
    r.add_argument("--provider", help="ollama | anthropic | openai | openai_compatible | litellm (default: $LBA_PROVIDER or ollama)")
    r.add_argument("--model", help="model name (default depends on provider)")
    r.add_argument("--base-url", help="API base URL / Ollama host")
    r.add_argument("--headless", action="store_true", default=None, help="run the browser headless")
    r.add_argument("--cdp-url", help="attach to a running browser via CDP instead of launching one")
    r.add_argument("--max-steps", type=int, help="maximum agent steps")
    r.add_argument("--timeout", type=float, help="overall timeout in seconds")
    r.add_argument("--start-url", help="navigate here before the agent starts (http(s):// URL with a host)")
    r.add_argument("--allowed-domain", "--allow-domain", action="append", dest="allowed_domains", help="restrict to this domain (repeatable)")
    r.add_argument("--json", action="store_true", help="print the RunResult as JSON")
    r.add_argument("--trace", metavar="PATH",
                   help="append every event as a JSON line to PATH (the directory must already exist)")
    r.add_argument("--no-preflight", action="store_true", help="skip the provider availability check")

    _add_log_args(r)

    m = sub.add_parser("mcp", prog="lba mcp", help="start the stdio MCP server (config from LBA_* env vars)")
    _add_log_args(m)
    m.add_argument("--strict", action="store_true",
                   help="exit 2 on an invalid LBA_* configuration instead of serving and reporting it per tool call "
                        "(same as LBA_MCP_STRICT=1)")
    ev = sub.add_parser("eval", help="run the evaluation suite (remaining args are forwarded)", add_help=False)
    ev.add_argument("rest", nargs=argparse.REMAINDER)
    return p


def _valid_url(url: str, schemes: tuple[str, ...]) -> bool:
    from urllib.parse import urlsplit

    try:
        parts = urlsplit(url.strip())
        return parts.scheme.lower() in schemes and bool(parts.hostname)
    except ValueError:
        return False


def _valid_cdp_url(url: str) -> bool:
    return _valid_url(url, ("http", "https", "ws", "wss"))


def _config_problems(exc: BaseException) -> list[str]:
    """One message per problem, without a repeated field name ("cdp_url: cdp_url must be ..." -> "cdp_url: must be ...")."""
    from local_browser_agent.log import format_validation_error

    out: list[str] = []
    for ln in format_validation_error(exc).splitlines():
        ln = ln.strip()
        if not ln:
            continue
        field, sep, msg = ln.partition(": ")
        leaf = field.rsplit(".", 1)[-1]
        if sep and msg.startswith(leaf + " "):
            ln = f"{field}: {msg[len(leaf) + 1:]}"
        out.append(ln)
    return out or [str(exc)]


class _DropRunFailedWarning(logging.Filter):
    """``run_task`` logs "run <id> failed (<kind>)" and the CLI prints the full message as an error."""

    _TEMPLATES = frozenset({"run %s failed (%s)", "run %s failed: %s"})

    def filter(self, record: logging.LogRecord) -> bool:
        return not (record.levelno == logging.WARNING and record.msg in self._TEMPLATES)


def _config_from_args(args: argparse.Namespace):
    """Env config plus flag overrides, validated as a whole (flags can never bypass validation)."""
    import os

    from local_browser_agent.config import AgentConfig

    if args.cdp_url is not None and not _valid_cdp_url(args.cdp_url):
        raise ValueError("invalid --cdp-url: expected an http(s):// or ws(s):// URL with a host, "
                         f"got {args.cdp_url!r}")
    if args.start_url is not None and not _valid_url(args.start_url, ("http", "https")):
        raise ValueError("invalid --start-url: expected an http(s):// URL with a host, "
                         f"got {args.start_url!r}")
    data = AgentConfig.from_env().model_dump()
    if args.provider:
        data["model"]["provider"] = args.provider.lower()
        # re-resolve provider-specific key fallback when provider was overridden
        provider = data["model"]["provider"]
        if data["model"].get("api_key") is None and provider in ("anthropic", "openai"):
            key = os.environ.get(f"{provider.upper()}_API_KEY")
            if key:
                data["model"]["api_key"] = key
    if args.model:
        data["model"]["model"] = args.model
    if args.base_url:
        data["model"]["base_url"] = args.base_url
    if args.headless:
        data["browser"]["headless"] = True
    if args.cdp_url is not None:
        data["browser"]["cdp_url"] = args.cdp_url.strip()
    if args.max_steps is not None:
        data["max_steps"] = args.max_steps
    if args.timeout is not None:
        data["timeout_s"] = args.timeout
    if args.allowed_domains:
        data["safety"]["allowed_domains"] = args.allowed_domains
    return AgentConfig.model_validate(data)


_CONFIG_FLAGS = ("provider", "model", "base_url", "cdp_url", "max_steps", "timeout", "allowed_domains",
                 "start_url", "api_key_env")


def _env_only_args(args: argparse.Namespace) -> argparse.Namespace:
    """``args`` with every flag that feeds the config cleared (so only ``LBA_*`` environment values remain).

    Used to tell an invalid flag value ("usage") from an invalid environment ("config")."""
    clean = argparse.Namespace(**vars(args))
    for name in _CONFIG_FLAGS:
        if hasattr(clean, name):
            setattr(clean, name, None)
    for name in ("headless", "headed"):
        if hasattr(clean, name):
            setattr(clean, name, False if name == "headed" else None)
    return clean


def _human_summary(result) -> str:
    """Stdout summary for humans; error messages go to stderr (see ``_cmd_run``)."""
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
    return "\n".join(lines)


def _log_settings(args: argparse.Namespace, default: str) -> tuple[str, str | None]:
    """(our level, third-party level). ``-q``: errors only from our logger and nothing from browser-use.
    ``--json`` behaves the same by default (the RunResult carries the errors). ``--log-level`` always
    wins and applies to everything."""
    if args.log_level:
        return args.log_level, None
    if args.quiet or getattr(args, "json", False):
        return "error", "off"
    return default, None


def _configure_logging(args: argparse.Namespace, default: str) -> None:
    from local_browser_agent.log import configure_logging

    level, third_party = _log_settings(args, default)
    configure_logging(level, third_party=third_party)


def _error_result(task: str, errors: list[str], status: str = "error", run_id: str | None = None,
                  error_kind: str | None = None) -> dict:
    from local_browser_agent.runner import RunResult

    result = RunResult(run_id=run_id or str(uuid.uuid4()), task=task, status=status, success=None,
                       errors=list(errors)).to_dict()
    result["error_kind"] = error_kind
    return result


def _fail(args: argparse.Namespace, message: str, code: int, *, status: str = "error", trace=None,
          error_kind: str | None = None, errors: list[str] | None = None) -> int:
    """Report a failure that happened before/outside a run: text on stderr, JSON on stdout.

    ``errors`` is the per-problem list for the JSON ``errors`` field (default: ``[message]``)."""
    run_id = str(uuid.uuid4())
    for line in (message.splitlines() or [message]):
        print(f"lba run: error: {line}", file=sys.stderr)
    if getattr(args, "json", False):
        print(json.dumps(_error_result(args.task, errors or [message], status, run_id, error_kind), indent=2))
    if trace is not None and trace.events_written == 0:
        from local_browser_agent.events import DoneEvent, ErrorEvent, StateEvent

        trace.run_id = run_id  # same id as the RunResult printed above

        async def write():
            for ev in (ErrorEvent(message=message), StateEvent(state="error"), DoneEvent()):
                try:
                    ev.run_id = run_id  # type: ignore[attr-defined]
                except Exception:  # pragma: no cover
                    pass
                await trace(ev)

        try:
            asyncio.run(write())
        except Exception:
            pass
    return code


def _open_trace(path: str):
    """Create the trace sink after proving the path is writable (raises OSError otherwise).

    The parent directory is never created: a missing one is an error."""
    from pathlib import Path

    from local_browser_agent.sinks import JsonlTraceSink

    p = Path(path)
    if not p.parent.is_dir():
        raise OSError(errno.ENOENT, "directory does not exist")
    with open(p, "a", encoding="utf-8"):
        pass
    return JsonlTraceSink(p)


def _usage_problem(args: argparse.Namespace) -> str | None:
    """Flag mistakes that must exit 2 before any pre-flight or config work."""
    if not (args.task or "").strip():
        return "the task must not be empty"
    for d in args.allowed_domains or []:
        if not d.strip():
            return "invalid --allowed-domain: must not be empty"
    if args.cdp_url is not None and not _valid_cdp_url(args.cdp_url):
        return ("invalid --cdp-url: expected an http(s):// or ws(s):// URL with a host, "
                f"got {args.cdp_url!r}")
    if args.start_url is not None and not _valid_url(args.start_url, ("http", "https")):
        return ("invalid --start-url: expected an http(s):// URL with a host, "
                f"got {args.start_url!r}")
    return None


def _cmd_run(args: argparse.Namespace) -> int:
    _configure_logging(args, "info")
    from local_browser_agent import run_task
    from local_browser_agent.models import PreFlightError, check_provider

    usage = _usage_problem(args)
    if usage:
        return _fail(args, usage, EXIT_USAGE, error_kind="usage")
    try:
        cfg = _config_from_args(args)
    except Exception as e:
        problems = _config_problems(e)
        message = "\n".join(f"invalid configuration: {p}" for p in problems)
        # A config that is valid from the environment alone means a flag caused this: "usage", else "config".
        try:
            _config_from_args(_env_only_args(args))
            kind = "usage"
        except Exception:
            kind = "config"
        return _fail(args, message, EXIT_USAGE, error_kind=kind, errors=problems)
    trace = None
    if args.trace:
        try:
            trace = _open_trace(args.trace)
        except OSError as e:
            return _fail(args, f"cannot write --trace {args.trace!r}: {e.strerror or e}", EXIT_USAGE,
                          error_kind="usage")
    sinks = [trace] if trace else []

    async def go():
        if not args.no_preflight:
            await check_provider(cfg.model)
        return await run_task(args.task, cfg, sinks=sinks, start_url=args.start_url)

    dup = _DropRunFailedWarning()
    lib_logger = logging.getLogger("local_browser_agent")
    lib_logger.addFilter(dup)
    try:
        result = asyncio.run(go())
    except PreFlightError as e:
        return _fail(args, str(e), EXIT_ENV, trace=trace, error_kind="preflight")
    except KeyboardInterrupt:
        return _fail(args, "interrupted", EXIT_INTERRUPTED, status="stopped", trace=trace, error_kind="stopped")
    finally:
        lib_logger.removeFilter(dup)
    if args.json:
        print(json.dumps(result.to_dict(), indent=2))
    else:
        print(_human_summary(result))
        for e in result.errors:
            print(f"lba run: error: {e}", file=sys.stderr)
    if result.status == "success":
        return EXIT_OK
    if result.error_kind == "config":
        return EXIT_USAGE  # invalid configuration found once the run started: same code as before it
    return EXIT_ENV if result.error_kind in ENV_ERROR_KINDS else EXIT_FAILED


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
    try:
        args = _build_parser().parse_args(argv)
    except _UsageError as e:
        if argv[:1] == ["run"] and _wants_json(argv):
            print(json.dumps(_error_result("", [e.message], error_kind="usage"), indent=2))
        e.parser.print_usage(sys.stderr)
        print(f"{e.parser.prog}: error: {e.message}", file=sys.stderr)
        return EXIT_USAGE
    if args.command == "run":
        from local_browser_agent.log import quiet_filters

        with quiet_filters():  # the CLI owns the process: browser-use failure noise dropped for the whole run
            return _cmd_run(args)
    if args.command == "mcp":
        from local_browser_agent.mcp_server import serve

        level, third_party = _log_settings(args, "warning")
        return serve(level, third_party=third_party, strict=True if args.strict else None)
    if args.command == "eval":
        return _cmd_eval(args.rest or [])
    return 2


if __name__ == "__main__":
    sys.exit(main())

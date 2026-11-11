"""Command line entry point: ``python -m local_browser_agent.evals.cli`` (later ``lba eval``)."""
from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any, Sequence

from .runner import DEFAULT_MAX_INFRA_ERRORS, INFRA_ERROR_KINDS
from .tasks import FINAL_SUFFIX, TASKS, get_tasks

PREFIX = "lba eval: error:"
EXIT_USAGE, EXIT_ENV = 2, 3  # same meaning as ``lba run``: 2 = bad flags/config, 3 = environment not ready

#: Flags that only apply to a real run; combining them with --compare/--list/--self-test is a usage error.
_RUN_ONLY_FLAGS = (
    ("provider", "--provider"), ("model", "--model"), ("api_key_env", "--api-key-env"),
    ("base_url", "--base-url"), ("tasks", "--tasks"), ("cdp_url", "--cdp-url"), ("max_steps", "--max-steps"),
    ("budget_minutes", "--budget-minutes"), ("fail_under", "--fail-under"),
)


def _err(msg: str) -> None:
    print(f"{PREFIX} {msg}", file=sys.stderr)


def _fail(args: argparse.Namespace, code: int, error_kind: str, errors: list[str], *, prefix: str = "",
          error_kinds: list[str] | None = None) -> int:
    """Report a failure: one ``lba eval: error:`` line per problem on stderr and, with --json, one JSON
    document on stdout (``{"status": "error", "error_kind": ..., "error_kinds": [...], "errors": [...]}``).
    ``error_kind`` is the first kind; ``error_kinds`` (all kinds, in order) is given when there are several."""
    for e in errors:
        _err(f"{prefix}{e}")
    if getattr(args, "json", False):
        doc: dict[str, Any] = {"status": "error", "error_kind": error_kind}
        if error_kinds is not None:
            doc["error_kinds"] = list(error_kinds)
        doc["errors"] = list(errors)
        print(json.dumps(doc, indent=2))
    return code


class _Parser(argparse.ArgumentParser):
    """argparse usage errors also produce the one JSON document under ``--json``."""

    def error(self, message: str) -> Any:  # type: ignore[override]
        argv = getattr(self, "_argv", None) or []
        # argparse accepts unique prefixes, so "--jso" counts as --json here too.
        if any(len(a) >= 4 and "--json".startswith(a.split("=", 1)[0]) and len(a.split("=", 1)[0]) >= 4
               for a in argv if a.startswith("--")):
            print(json.dumps({"status": "error", "error_kind": "usage", "errors": [message]}, indent=2))
        super().error(message)


def build_parser() -> argparse.ArgumentParser:
    p = _Parser(
        prog="lba eval", description="Deterministic eval suite for the browser agent."
    )
    p.add_argument("--self-test", action="store_true", help="validate fixtures and checkers (no browser, no LLM)")
    p.add_argument("--list", action="store_true", help="list task ids, categories and instructions")
    p.add_argument(
        "--compare",
        nargs=2,
        metavar=("BASELINE", "CANDIDATE"),
        help="compare two results.json files (exit 1 regression, 2 invalid comparison; see docs/EVALS.md)",
    )
    p.add_argument("--tolerance", type=float, default=0.0, metavar="PP", help="--compare: allowed per-task pass-rate drop, 0 to 1 (default 0)")
    p.add_argument("--score-tolerance", type=float, default=0.1, metavar="D", help="--compare: allowed per-task mean-score drop (default 0.1)")
    p.add_argument("--min-n", type=int, default=None, metavar="N", help="--compare: exit 2 when a task has fewer than N runs on either side (default: the candidate needs at least as many runs per task as the baseline had)")
    p.add_argument("--allow-taskset-change", action="store_true", help="--compare: only warn when the task set/checker hash differs (default: exit 2)")
    p.add_argument("--strict", action="store_true", help="--compare: also exit 1 on warnings (steps/cost up 50%%, differing n, model, ...)")
    p.add_argument("-q", "--quiet", action="store_true", help="errors only on stderr: no progress lines or summary")
    p.add_argument("--json", action="store_true", help="print the final result (run summary, --compare, --list or --self-test) as one JSON document on stdout; human text goes to stderr")
    p.add_argument("--max-infra-errors", type=int, default=DEFAULT_MAX_INFRA_ERRORS, metavar="N", help=f"abort the run (exit 3) after N consecutive infrastructure errors such as a missing Chrome or CDP failure; 0 disables (default {DEFAULT_MAX_INFRA_ERRORS})")
    p.add_argument("--provider", help="model provider, e.g. anthropic, openai, ollama (default: $LBA_PROVIDER)")
    p.add_argument("--model", help="model name (default: $LBA_MODEL)")
    p.add_argument("--api-key-env", metavar="NAME", help="name of the environment variable holding the API key (default: $LBA_API_KEY)")
    p.add_argument("--base-url", help="model API base URL, e.g. http://localhost:11434 for Ollama (default: $LBA_BASE_URL)")
    p.add_argument("--cdp-url", help="attach to a running browser via CDP instead of launching Chrome")
    p.add_argument("--max-steps", type=int, help="override every task's step budget (1 to 500)")
    p.add_argument("--tasks", help="comma-separated task ids (default: all)")
    p.add_argument("--repeats", type=int, default=1, help="runs per task (default 1)")
    p.add_argument("--timeout", type=float, default=180.0, help="per-run timeout in seconds (default 180)")
    p.add_argument(
        "--budget-minutes",
        type=float,
        metavar="MIN",
        help="stop starting new runs after MIN minutes of wall-clock time (result is then incomplete, exit 1)",
    )
    p.add_argument("--out", default="eval-results", help="output directory (default eval-results)")
    p.add_argument("--headed", action="store_true", help="show the browser (default: headless)")
    p.add_argument(
        "--fail-under",
        type=float,
        metavar="RATE",
        help="exit 1 when the success rate is below RATE (0 to 1), for CI",
    )
    p.add_argument(
        "--fail-on-violation",
        action="store_true",
        help="exit 1 when any safety trap was triggered, for CI",
    )
    return p


def _print_table(headers: list[str], rows: list[list[str]]) -> None:
    widths = [max(len(h), *(len(r[i]) for r in rows)) if rows else len(h) for i, h in enumerate(headers)]
    fmt = "  ".join(f"{{:<{w}}}" for w in widths)
    print(fmt.format(*headers))
    print(fmt.format(*("-" * w for w in widths)))
    for r in rows:
        print(fmt.format(*r))


def _cmd_list(args: argparse.Namespace) -> int:
    if args.json:
        print(json.dumps([
            {"id": t.id, "category": t.category, "safety": t.safety, "max_steps": t.max_steps,
             "instruction": t.instruction, "final_suffix": " ".join(FINAL_SUFFIX.split())}
            for t in TASKS
        ], indent=2))
        return 0
    for t in TASKS:
        print(f"{t.id}  [{t.category}]{' (safety)' if t.safety else ''}")
        print(f"    {t.instruction}")
        print(f"    {' '.join(FINAL_SUFFIX.split())}")
    return 0


def _labels(a_path: str, b_path: str) -> tuple[str, str]:
    """Distinct column headers: ``parent/stem`` of each file, or baseline/candidate when those collide."""
    def one(p: str) -> str:
        path = Path(p)
        return f"{path.parent.name}/{path.stem}" if path.parent.name else path.stem

    a, b = one(a_path), one(b_path)
    return ("baseline", "candidate") if a == b else (a, b)


def _cmd_compare(a_path: str, b_path: str, args: argparse.Namespace) -> int:
    from .compare import CompareError, compare_results, load_results, render_comparison  # noqa: PLC0415

    try:
        cmp = compare_results(
            load_results(a_path),
            load_results(b_path),
            tolerance=args.tolerance,
            score_tolerance=args.score_tolerance,
            min_n=args.min_n,
            allow_taskset_change=args.allow_taskset_change,
            strict=args.strict,
        )
    except (CompareError, KeyError, TypeError, ValueError) as exc:
        return _fail(args, EXIT_USAGE, "invalid_input", [str(exc)])
    if args.json:
        print(json.dumps(cmp.to_dict(), indent=2))
        if not args.quiet:
            print(render_comparison(cmp, *_labels(a_path, b_path)), file=sys.stderr)
    elif not args.quiet:
        print(render_comparison(cmp, *_labels(a_path, b_path)))
    return cmp.exit_code


def _cmd_self_test(args: argparse.Namespace) -> int:
    from .selftest import run_self_test  # noqa: PLC0415

    res = run_self_test()
    if args.json:
        print(json.dumps({
            "ok": res.ok,
            "tasks": [
                {"task_id": o.task_id, "oracle_passed": o.oracle_passed, "oracle_score": o.oracle_score,
                 "null_failed": o.null_failed, "reckless_failed": o.reckless_failed, "ok": o.ok, "notes": list(o.notes)}
                for o in res.outcomes
            ],
            "site_problems": list(res.site_problems),
        }, indent=2))
        return 0 if res.ok else 1
    rows = []
    for o in res.outcomes:
        rows.append(
            [
                o.task_id,
                "yes" if o.oracle_passed and o.oracle_score == 1.0 else "NO",
                "yes" if o.null_failed else "NO",
                "n/a" if o.reckless_failed is None else ("yes" if o.reckless_failed else "NO"),
                "ok" if o.ok else "FAIL",
            ]
        )
    _print_table(["task", "oracle passes", "null fails", "reckless fails", "result"], rows)
    for o in res.outcomes:
        for n in o.notes:
            print(f"  {o.task_id}: {n}")
    for prob in res.site_problems:
        print(f"  site: {prob}")
    print(f"\nself-test: {'OK' if res.ok else 'FAILED'} ({len(res.outcomes)} tasks)")
    return 0 if res.ok else 1


def _build_config(args: argparse.Namespace, api_key: str | None) -> Any:
    """Start from ``LBA_*`` environment variables (like ``lba run``); flags override them."""
    from pydantic import SecretStr  # noqa: PLC0415

    from local_browser_agent import AgentConfig  # noqa: PLC0415

    from local_browser_agent import BrowserConfig, ModelConfig  # noqa: PLC0415

    cfg = AgentConfig.from_env()
    update: dict[str, Any] = {f: getattr(cfg.model, f) for f in type(cfg.model).model_fields}
    if args.provider:
        update["provider"] = args.provider.lower()
        if api_key is None and cfg.model.api_key is None and update["provider"] in ("anthropic", "openai"):
            api_key = os.environ.get(f"{update['provider'].upper()}_API_KEY")
    if args.model:
        update["model"] = args.model
    if args.base_url:
        update["base_url"] = args.base_url
    if api_key:
        update["api_key"] = SecretStr(api_key)
    # Validate the model settings as a whole (validate_assignment rejects field-by-field edits).
    model = ModelConfig.model_validate(update)
    bupdate = {f: getattr(cfg.browser, f) for f in type(cfg.browser).model_fields}
    bupdate["headless"] = not args.headed
    if getattr(args, "cdp_url", None) is not None:
        bupdate["cdp_url"] = args.cdp_url.strip()
    browser = BrowserConfig.model_validate(bupdate)
    cfg = cfg.model_copy(update={"model": model, "browser": browser})
    return cfg


def _print_summary(result: Any, file: Any = None) -> None:
    file = file or sys.stdout
    _print = lambda *a: print(*a, file=file)  # noqa: E731
    cost = result.total_cost_usd
    _print(f"\nmodel: {result.provider}/{result.model}   runs: {result.total_runs}")
    if result.runs and all(r.infra_error for r in result.runs):
        _print("no valid runs (infra errors)")
        return
    _print(f"success rate:      {'n/a' if result.success_rate is None else f'{result.success_rate * 100:.0f}%'}")
    _print(f"mean score:        {'n/a' if result.mean_score is None else f'{result.mean_score:.2f}'}")
    _print(f"safety violations: {result.safety_violations}")
    _print(f"mean steps:        {result.mean_steps:.1f}")
    _print(f"mean duration:     {result.mean_duration_s:.1f}s")
    _print(f"total cost:        {'n/a' if cost is None else f'${cost:.4f}'}")
    for cat, rate in result.category_pass_rates.items():
        _print(f"  {cat:<12} {'n/a' if rate is None else f'{rate * 100:.0f}%'}")


def preflight_problems(config: Any) -> list[str]:
    """Check Chrome and the model provider once, before any task runs. Never launches a browser."""
    from local_browser_agent.chrome import CHROME_NOT_FOUND_MESSAGE, find_chrome  # noqa: PLC0415

    problems: list[str] = []
    browser = getattr(config, "browser", None)
    cdp_url = getattr(browser, "cdp_url", None)
    exe = getattr(browser, "executable_path", None)
    if cdp_url:
        pass  # attaching to a running browser; nothing to locate
    elif exe:
        if not (os.path.isfile(exe) and os.access(exe, os.X_OK)):
            problems.append(f"browser executable_path {exe!r} does not exist or is not executable")
    elif find_chrome(getattr(browser, "channel", "chrome")) is None:
        problems.append(CHROME_NOT_FOUND_MESSAGE)
    model = getattr(config, "model", None)
    if model is not None:
        from local_browser_agent.models import PreFlightError, check_provider  # noqa: PLC0415

        try:
            asyncio.run(check_provider(model))
        except PreFlightError as exc:
            problems.append(str(exc))
        except Exception as exc:  # noqa: BLE001 - any failure to reach the provider is a pre-flight failure
            problems.append(f"provider check failed: {type(exc).__name__}: {exc}")
    return problems


def main(
    argv: Sequence[str] | None = None, *, run_fn: Any = None, config: Any = None, preflight: Any = None
) -> int:
    """CLI entry (see :func:`_main`); holds the quiet-log filters for a real run."""
    if config is not None:
        return _main(argv, run_fn=run_fn, config=config, preflight=preflight)
    from local_browser_agent.log import quiet_filters  # noqa: PLC0415

    with quiet_filters():
        return _main(argv, run_fn=run_fn, config=config, preflight=preflight)


def _main(
    argv: Sequence[str] | None = None, *, run_fn: Any = None, config: Any = None, preflight: Any = None
) -> int:
    """CLI entry. ``run_fn`` / ``config`` / ``preflight`` are injection points for tests.

    Exit codes: 0 ok; 1 a gate failed (``--fail-under``, ``--fail-on-violation``), the run was
    incomplete, or every run errored; 2 bad arguments/config or an invalid ``--compare``;
    3 environment not ready (no Chrome, provider unreachable, CDP failure, or the fail-fast stop
    after repeated infrastructure errors), like ``lba run``. With ``--json`` stdout always holds
    exactly one JSON document, ``{"status": "error", "error_kind": ..., "errors": [...]}`` on failure.
    """
    parser = build_parser()
    parser._argv = list(sys.argv[1:] if argv is None else argv)  # type: ignore[attr-defined]
    args = parser.parse_args(argv)

    def usage(msg: str) -> int:
        return _fail(args, EXIT_USAGE, "usage", [msg])

    if sum(bool(x) for x in (args.compare, args.list, args.self_test)) > 1:
        return usage("choose one of --compare, --list, --self-test")
    if args.compare:
        ignored = [flag for dest, flag in _RUN_ONLY_FLAGS if getattr(args, dest) not in (None, parser.get_default(dest))]
        ignored += [flag for dest, flag in (("repeats", "--repeats"), ("timeout", "--timeout"), ("out", "--out"),
                                            ("max_infra_errors", "--max-infra-errors"))
                    if getattr(args, dest) != parser.get_default(dest)]
        ignored += [flag for dest, flag in (("headed", "--headed"), ("fail_on_violation", "--fail-on-violation"))
                    if getattr(args, dest)]
        if ignored:
            return usage(f"--compare does not run anything; these flags would be ignored: {', '.join(ignored)}")
        for dest, flag in (("tolerance", "--tolerance"), ("score_tolerance", "--score-tolerance")):
            v = getattr(args, dest)
            if not math.isfinite(v) or not 0.0 <= v <= 1.0:
                return usage(f"{flag} must be between 0 and 1")
        if args.min_n is not None and args.min_n < 1:
            return usage("--min-n must be >= 1")
        return _cmd_compare(*args.compare, args)
    if args.list:
        return _cmd_list(args)
    if args.self_test:
        return _cmd_self_test(args)

    task_ids = [t.strip() for t in args.tasks.split(",") if t.strip()] if args.tasks else None
    try:
        get_tasks(task_ids)
    except KeyError as exc:
        return usage(str(exc.args[0]))
    if args.repeats < 1:
        return usage("--repeats must be >= 1")
    if args.fail_under is not None and not 0.0 <= args.fail_under <= 1.0:
        return usage("--fail-under must be between 0 and 1")
    if args.max_infra_errors < 0:
        return usage("--max-infra-errors must be >= 0")
    if args.timeout <= 0:
        return usage("--timeout must be > 0")
    if args.budget_minutes is not None and args.budget_minutes <= 0:
        return usage("--budget-minutes must be > 0")
    if args.max_steps is not None and not 1 <= args.max_steps <= 500:
        return usage("--max-steps must be between 1 and 500")
    if args.cdp_url is not None:
        from local_browser_agent.cli import _valid_cdp_url  # noqa: PLC0415

        if not _valid_cdp_url(args.cdp_url):
            return usage(f"invalid --cdp-url: expected an http(s):// or ws(s):// URL with a host, got {args.cdp_url!r}")

    real_run = config is None
    if real_run:
        from local_browser_agent.log import configure_logging  # noqa: PLC0415

        quiet_logs = args.quiet or args.json
        configure_logging("error" if quiet_logs else "warning", third_party="off" if quiet_logs else None)
    if config is None:
        if not (args.provider or os.environ.get("LBA_PROVIDER")) or not (args.model or os.environ.get("LBA_MODEL")):
            return _fail(args, EXIT_USAGE, "config", [
                "a provider and model are required for a real run "
                "(--provider/--model or LBA_PROVIDER/LBA_MODEL)"])
        api_key = None
        if args.api_key_env:
            api_key = os.environ.get(args.api_key_env)
            if not api_key:
                return _fail(args, EXIT_USAGE, "config", [f"environment variable {args.api_key_env} is not set"])
        try:
            config = _build_config(args, api_key)
        except ValueError as exc:  # pydantic.ValidationError is a ValueError
            from local_browser_agent.cli import _config_problems  # noqa: PLC0415

            return _fail(args, EXIT_USAGE, "config", _config_problems(exc), prefix="invalid configuration: ")

    if real_run or preflight is not None:
        problems = (preflight or preflight_problems)(config)
        if problems:
            from local_browser_agent.chrome import CHROME_NOT_FOUND_MESSAGE  # noqa: PLC0415

            kinds = ["chrome_missing" if p == CHROME_NOT_FOUND_MESSAGE else "preflight" for p in problems]
            kinds = list(dict.fromkeys(kinds))
            # the first problem's kind leads (chrome is checked before the provider)
            _fail(args, EXIT_ENV, kinds[0], problems, prefix="pre-flight failed: ", error_kinds=kinds)
            print("no tasks were run", file=sys.stderr)
            return EXIT_ENV

    from .runner import run_suite  # noqa: PLC0415

    human = sys.stderr if args.json else sys.stdout

    def progress(rec: Any) -> None:
        if args.quiet:
            return
        if rec.error_kind in INFRA_ERROR_KINDS:  # one line; details are in the result file
            print(f"[INFRA] {rec.task_id} #{rec.repeat} {rec.error_kind}", file=human, flush=True)
            return
        flag = "PASS" if rec.passed else "FAIL"
        print(f"[{flag}] {rec.task_id} #{rec.repeat} score={rec.score:.2f} steps={rec.steps}", file=human, flush=True)

    out_dir = Path(args.out)
    out_existed = out_dir.exists()
    # A pre-existing --out is never touched unless the result is kept: run into a staging directory beside
    # it and move the files over afterwards.
    run_dir = Path(tempfile.mkdtemp(prefix=f".{out_dir.name}.staging-", dir=out_dir.resolve().parent)) \
        if out_existed else out_dir
    result = asyncio.run(
        run_suite(
            config,
            task_ids=task_ids,
            repeats=args.repeats,
            out_dir=run_dir,
            run_fn=run_fn,
            progress=progress,
            timeout_s=args.timeout,
            budget_s=args.budget_minutes * 60 if args.budget_minutes else None,
            max_infra_errors=args.max_infra_errors,
            max_steps=args.max_steps,
        )
    )
    infra_kinds = _all_infra_kinds(result)
    if infra_kinds:
        # Every run failed for environment reasons: nothing worth keeping, and no results dir left behind
        # (a pre-existing one keeps its old files).
        shutil.rmtree(run_dir, ignore_errors=True)
        errors = [result.meta["infra_abort"]] if result.meta.get("infra_abort") else []
        errors += list(dict.fromkeys(e for r in result.runs for e in r.errors if e))[:5]
        if not errors:
            errors = [f"every run failed with {', '.join(infra_kinds)}; no valid results"]
        if not args.quiet:
            _print_summary(result, human)
        # Only bad configuration: a usage problem (exit 2), as in ``lba run``; anything else is the environment (3).
        code = EXIT_USAGE if infra_kinds == ["config"] else EXIT_ENV
        return _fail(args, code, infra_kinds[0], errors,
                     error_kinds=infra_kinds if len(infra_kinds) > 1 else None)
    if run_dir != out_dir:
        for item in run_dir.iterdir():
            dest = out_dir / item.name
            if dest.is_dir() and not dest.is_symlink():
                shutil.rmtree(dest)
            shutil.move(str(item), str(dest))
        shutil.rmtree(run_dir, ignore_errors=True)
    out_path = str(out_dir.resolve())
    if not args.quiet:
        _print_summary(result, human)
        print(f"\nreports written to {out_path}", file=sys.stderr)
    if args.json:
        doc = result.to_dict()
        doc["out"] = out_path
        print(json.dumps(doc, indent=2))
    return _gate(result, args)


def _all_infra_kinds(result: Any) -> list[str]:
    """Distinct ``error_kind`` values (in order) when every run failed for an environment reason, else ``[]``."""
    if not result.runs or not all(r.error_kind in INFRA_ERROR_KINDS for r in result.runs):
        return []
    return list(dict.fromkeys(r.error_kind for r in result.runs))


def _gate(result: Any, args: argparse.Namespace) -> int:
    """Exit code for CI: 1 when a requested threshold is missed, else 0."""
    code = 0
    if result.meta.get("infra_abort"):
        print(f"gate: {result.meta['infra_abort']}", file=sys.stderr)
        return EXIT_ENV
    if result.runs and all(r.status == "error" or r.infra_error for r in result.runs):
        print("gate: every run errored; the results say nothing about the model", file=sys.stderr)
        code = 1
    if not result.meta.get("complete", True):
        print("gate: run stopped early (--budget-minutes); results are partial", file=sys.stderr)
        code = 1
    if args.fail_on_violation and result.safety_violations:
        print(f"gate: {result.safety_violations} safety violation(s)", file=sys.stderr)
        code = 1
    if args.fail_under is not None and result.has_valid_runs and result.success_rate < args.fail_under:
        print(
            f"gate: success rate {result.success_rate:.2f} is below {args.fail_under:.2f}",
            file=sys.stderr,
        )
        code = 1
    return code


if __name__ == "__main__":
    sys.exit(main())

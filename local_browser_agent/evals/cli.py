"""Command line entry point: ``python -m local_browser_agent.evals.cli`` (later ``lba eval``)."""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path
from typing import Any, Sequence

from .tasks import TASKS, get_tasks


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="lba eval", description="Deterministic eval suite for the browser agent."
    )
    p.add_argument("--self-test", action="store_true", help="validate fixtures and checkers (no browser, no LLM)")
    p.add_argument("--list", action="store_true", help="list task ids, categories and instructions")
    p.add_argument("--provider", help="model provider, e.g. anthropic, openai, ollama")
    p.add_argument("--model", help="model name")
    p.add_argument("--api-key-env", metavar="NAME", help="name of the environment variable holding the API key")
    p.add_argument("--base-url", help="model API base URL (e.g. http://localhost:11434 for Ollama)")
    p.add_argument("--tasks", help="comma-separated task ids (default: all)")
    p.add_argument("--repeats", type=int, default=1, help="runs per task (default 1)")
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


def _cmd_list() -> int:
    for t in TASKS:
        print(f"{t.id}  [{t.category}]{' (safety)' if t.safety else ''}")
        print(f"    {t.instruction}")
    return 0


def _cmd_self_test() -> int:
    from .selftest import run_self_test  # noqa: PLC0415

    res = run_self_test()
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
    from local_browser_agent import (  # noqa: PLC0415
        AgentConfig,
        BrowserConfig,
        ModelConfig,
        SafetyPolicy,
    )

    return AgentConfig(
        model=ModelConfig(provider=args.provider, model=args.model, api_key=api_key, base_url=args.base_url),
        browser=BrowserConfig(headless=not args.headed),
        safety=SafetyPolicy(),
    )


def _print_summary(result: Any) -> None:
    cost = result.total_cost_usd
    print(f"\nmodel: {result.provider}/{result.model}   runs: {result.total_runs}")
    print(f"success rate:      {result.success_rate * 100:.0f}%")
    print(f"mean score:        {result.mean_score:.2f}")
    print(f"safety violations: {result.safety_violations}")
    print(f"mean steps:        {result.mean_steps:.1f}")
    print(f"mean duration:     {result.mean_duration_s:.1f}s")
    print(f"total cost:        {'n/a' if cost is None else f'${cost:.4f}'}")
    for cat, rate in result.category_pass_rates.items():
        print(f"  {cat:<12} {rate * 100:.0f}%")


def main(argv: Sequence[str] | None = None, *, run_fn: Any = None, config: Any = None) -> int:
    """CLI entry. ``run_fn`` / ``config`` are injection points for tests."""
    args = build_parser().parse_args(argv)

    if args.list:
        return _cmd_list()
    if args.self_test:
        return _cmd_self_test()

    task_ids = [t.strip() for t in args.tasks.split(",") if t.strip()] if args.tasks else None
    try:
        get_tasks(task_ids)
    except KeyError as exc:
        print(f"error: {exc.args[0]}", file=sys.stderr)
        return 2
    if args.repeats < 1:
        print("error: --repeats must be >= 1", file=sys.stderr)
        return 2
    if args.fail_under is not None and not 0.0 <= args.fail_under <= 1.0:
        print("error: --fail-under must be between 0 and 1", file=sys.stderr)
        return 2

    if config is None:
        if not args.provider or not args.model:
            print("error: --provider and --model are required for a real run", file=sys.stderr)
            return 2
        api_key = None
        if args.api_key_env:
            api_key = os.environ.get(args.api_key_env)
            if not api_key:
                print(f"error: environment variable {args.api_key_env} is not set", file=sys.stderr)
                return 2
        config = _build_config(args, api_key)

    from .runner import run_suite  # noqa: PLC0415

    def progress(rec: Any) -> None:
        flag = "PASS" if rec.passed else "FAIL"
        print(f"[{flag}] {rec.task_id} #{rec.repeat} score={rec.score:.2f} steps={rec.steps}", flush=True)

    result = asyncio.run(
        run_suite(
            config,
            task_ids=task_ids,
            repeats=args.repeats,
            out_dir=Path(args.out),
            run_fn=run_fn,
            progress=progress,
        )
    )
    _print_summary(result)
    print(f"\nreports written to {Path(args.out).resolve()}")
    return _gate(result, args)


def _gate(result: Any, args: argparse.Namespace) -> int:
    """Exit code for CI: 1 when a requested threshold is missed, else 0."""
    code = 0
    if args.fail_on_violation and result.safety_violations:
        print(f"gate: {result.safety_violations} safety violation(s)", file=sys.stderr)
        code = 1
    if args.fail_under is not None and result.success_rate < args.fail_under:
        print(
            f"gate: success rate {result.success_rate:.2f} is below {args.fail_under:.2f}",
            file=sys.stderr,
        )
        code = 1
    return code


if __name__ == "__main__":
    sys.exit(main())

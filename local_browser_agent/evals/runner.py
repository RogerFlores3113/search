"""Run the eval suite against a real (or injected fake) ``run_task``."""
from __future__ import annotations

import asyncio
import copy
import datetime as _dt
import os
import subprocess
import time
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable

from .server import FIXTURE_HOST, FixtureServer
from .tasks import CHECKER_VERSION, EvalTask, get_tasks, task_hash, taskset_hash

SCHEMA_VERSION = 1

RunFn = Callable[..., Awaitable[Any]]
DEFAULT_MAX_INFRA_ERRORS = 2
_HARD_STOP_GRACE_S = 30.0


def _lazy_run_task() -> RunFn:
    """Import the library lazily so this module imports without ``local_browser_agent`` __init__."""
    from local_browser_agent import run_task  # noqa: PLC0415

    return run_task


#: ``error_kind`` values that mean the environment, not the model, failed.
INFRA_ERROR_KINDS = frozenset({"chrome_missing", "preflight", "cdp_connect", "config"})


def is_infra_error(status: str | None, error_kind: str | None) -> bool:
    """A run that says nothing about the model: errored, timed out, or failed to set up."""
    return status in ("error", "timeout") or error_kind in INFRA_ERROR_KINDS


@dataclass
class RunRecord:
    task_id: str
    category: str
    safety: bool
    repeat: int
    passed: bool
    score: float
    status: str
    steps: int
    duration_s: float
    cost_usd: float | None
    safety_violation: bool
    notes: str
    answer: str
    blocked_actions: int = 0
    errors: list[str] = field(default_factory=list)
    error_kind: str | None = None

    @property
    def infra_error(self) -> bool:
        return is_infra_error(self.status, self.error_kind)


@dataclass
class SuiteResult:
    runs: list[RunRecord]
    provider: str | None = None
    model: str | None = None
    timestamp: str = ""
    meta: dict[str, Any] = field(default_factory=dict)

    @property
    def total_runs(self) -> int:
        return len(self.runs)

    @property
    def success_rate(self) -> float | None:
        """Pass rate over all runs; ``None`` when there are no valid (non-infra) runs."""
        if not self.has_valid_runs:
            return None
        return sum(r.passed for r in self.runs) / len(self.runs)

    @property
    def mean_score(self) -> float | None:
        """Mean score over all runs; ``None`` when there are no valid (non-infra) runs."""
        if not self.has_valid_runs:
            return None
        return sum(r.score for r in self.runs) / len(self.runs)

    @property
    def category_pass_rates(self) -> dict[str, float | None]:
        """Pass rate per category; ``None`` for a category whose runs were all infra errors."""
        buckets: dict[str, list[RunRecord]] = defaultdict(list)
        for r in self.runs:
            buckets[r.category].append(r)
        return {
            c: (sum(r.passed for r in v) / len(v) if any(not r.infra_error for r in v) else None)
            for c, v in sorted(buckets.items())
        }

    @property
    def safety_violations(self) -> int:
        return sum(r.safety_violation for r in self.runs)

    @property
    def mean_steps(self) -> float:
        return sum(r.steps for r in self.runs) / len(self.runs) if self.runs else 0.0

    @property
    def mean_duration_s(self) -> float:
        return sum(r.duration_s for r in self.runs) / len(self.runs) if self.runs else 0.0

    @property
    def total_cost_usd(self) -> float | None:
        costs = [r.cost_usd for r in self.runs if r.cost_usd is not None]
        return sum(costs) if costs else None

    def task_summaries(self) -> dict[str, dict[str, Any]]:
        """Per-task aggregate across repeats, in first-seen order."""
        by_task: dict[str, list[RunRecord]] = {}
        for r in self.runs:
            by_task.setdefault(r.task_id, []).append(r)
        out: dict[str, dict[str, Any]] = {}
        for tid, rs in by_task.items():
            n = len(rs)
            costs = [r.cost_usd for r in rs if r.cost_usd is not None]
            passes = sum(r.passed for r in rs)
            out[tid] = {
                "category": rs[0].category,
                "safety": rs[0].safety,
                "n": n,
                "passes": passes,
                "pass_rate": passes / n,
                "mean_score": sum(r.score for r in rs) / n,
                "mean_steps": sum(r.steps for r in rs) / n,
                "mean_duration_s": sum(r.duration_s for r in rs) / n,
                "cost_usd": sum(costs) if costs else None,
                "safety_violations": sum(r.safety_violation for r in rs),
                "infra_errors": sum(r.infra_error for r in rs),
            }
        return out

    @property
    def has_valid_runs(self) -> bool:
        """False when there are no runs or every run was an infrastructure error."""
        return any(not r.infra_error for r in self.runs)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "meta": self.meta,
            "provider": self.provider,
            "model": self.model,
            "timestamp": self.timestamp,
            "summary": {
                "total_runs": self.total_runs,
                "success_rate": self.success_rate,
                "mean_score": self.mean_score,
                "category_pass_rates": self.category_pass_rates,
                "safety_violations": self.safety_violations,
                "mean_steps": self.mean_steps,
                "mean_duration_s": self.mean_duration_s,
                "total_cost_usd": self.total_cost_usd,
            },
            "tasks": self.task_summaries(),
            "runs": [asdict(r) for r in self.runs],
        }


def _config_for_run(config: Any, task: EvalTask, host: str, timeout_s: float | None = None,
                    max_steps: int | None = None) -> Any:
    """Copy ``config`` (never mutate the caller's) and restrict navigation to the fixture host."""
    cfg = copy.deepcopy(config)
    try:
        cfg.safety.allowed_domains = [host]
    except Exception:  # frozen models: rebuild via pydantic model_copy
        safety = cfg.safety.model_copy(update={"allowed_domains": [host]})
        cfg = cfg.model_copy(update={"safety": safety})
    try:  # fixtures are served from 127.0.0.1, so the local-network block must be off
        cfg.safety.allow_local_network = True
    except Exception:
        pass
    if timeout_s is not None and hasattr(cfg, "timeout_s"):
        try:
            cfg.timeout_s = timeout_s
        except Exception:
            pass
    # Best effort: apply the per-task step budget when the config exposes one.
    if hasattr(cfg, "max_steps"):
        try:
            cfg.max_steps = max_steps if max_steps is not None else task.max_steps
        except Exception:
            pass
    return cfg


def _model_info(config: Any) -> tuple[str | None, str | None]:
    model = getattr(config, "model", None)
    return getattr(model, "provider", None), getattr(model, "model", None)


def _git_sha() -> str | None:
    sha = os.environ.get("GITHUB_SHA")
    if sha:
        return sha
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=Path(__file__).resolve().parent,
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    sha = out.stdout.strip()
    return sha if out.returncode == 0 and sha else None


def _lba_version() -> str | None:
    from importlib import metadata  # noqa: PLC0415

    try:
        return metadata.version("local-browser-agent")
    except metadata.PackageNotFoundError:
        return None


def build_meta(
    config: Any, tasks: list[EvalTask], repeats: int, timeout_s: float | None, provider: str | None, model: str | None
) -> dict[str, Any]:
    """Run metadata that makes two results files comparable (or shows why they are not)."""
    return {
        "git_sha": _git_sha(),
        "lba_version": _lba_version(),
        "taskset_hash": taskset_hash(tasks),
        "task_hashes": {t.id: task_hash(t) for t in tasks},
        "checker_version": CHECKER_VERSION,
        "task_ids": [t.id for t in tasks],
        "max_steps": {t.id: t.max_steps for t in tasks},
        "timeout_s": timeout_s,
        "repeats": repeats,
        "provider": provider,
        "model": model,
        "planned_runs": len(tasks) * repeats,
        "complete": False,
    }


async def run_suite(
    config: Any,
    task_ids: list[str] | None = None,
    repeats: int = 1,
    out_dir: Path | None = Path("eval-results"),
    run_fn: RunFn | None = None,
    progress: Callable[[RunRecord], None] | None = None,
    timeout_s: float | None = None,
    budget_s: float | None = None,
    max_infra_errors: int | None = DEFAULT_MAX_INFRA_ERRORS,
    max_steps: int | None = None,
) -> SuiteResult:
    """Run each selected task ``repeats`` times against a fresh fixture state.

    ``run_fn`` defaults to the library's ``run_task`` (imported lazily). Pass ``out_dir=None``
    to skip writing reports. ``timeout_s`` caps each run (the config's ``timeout_s`` plus an outer
    hard stop). With ``out_dir``, every run is appended to ``results.jsonl`` and ``results.json`` /
    ``results.md`` are rewritten after each task, so a crash keeps partial results.
    ``budget_s`` stops launching new runs once that much wall-clock time has passed; the result
    is then marked ``meta["complete"] = False``. After ``max_infra_errors`` consecutive runs that
    failed for environment reasons (``INFRA_ERROR_KINDS``: no Chrome, CDP, pre-flight, config) the
    remaining runs are skipped: ``meta["complete"] = False``, ``meta["stopped_reason"] =
    "infra_errors"`` and ``meta["infra_abort"]`` holds the one-line explanation (``None`` disables).
    """
    tasks = get_tasks(task_ids)
    run = run_fn or _lazy_run_task()
    provider, model = _model_info(config)
    repeats = max(1, repeats)
    records: list[RunRecord] = []
    meta = build_meta(config, tasks, repeats, timeout_s, provider, model)
    if max_steps is not None:  # --max-steps overrides every task's own budget
        meta["max_steps"] = {t.id: max_steps for t in tasks}
        meta["max_steps_override"] = max_steps
    result = SuiteResult(
        runs=records,
        provider=provider,
        model=model,
        timestamp=_dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds"),
        meta=meta,
    )
    report = None
    if out_dir is not None:
        from . import report  # noqa: PLC0415

        report.reset_jsonl(Path(out_dir))

    started = time.monotonic()
    out_of_budget = False
    infra_streak = 0
    infra_abort: str | None = None
    with FixtureServer() as server:
        for task in tasks:
            for rep in range(1, repeats + 1):
                if budget_s is not None and time.monotonic() - started >= budget_s:
                    out_of_budget = True
                    break
                server.reset()
                instruction = task.render(server.base_url)
                rec = await _run_one(run, config, task, rep, instruction, server, timeout_s, max_steps)
                records.append(rec)
                infra_streak = infra_streak + 1 if rec.error_kind in INFRA_ERROR_KINDS else 0
                if report:
                    report.append_run(rec, Path(out_dir))
                if progress:
                    progress(rec)
                if max_infra_errors and infra_streak >= max_infra_errors:
                    infra_abort = (
                        f"aborting: {infra_streak} consecutive infrastructure errors "
                        f"({rec.error_kind}); the environment is broken, see the result file"
                    )
                    break
            if out_of_budget or infra_abort:
                break
            if report:
                report.write_report(result, Path(out_dir))

    meta["complete"] = not out_of_budget and not infra_abort
    if out_of_budget:
        meta["stopped_reason"] = "budget"
    if infra_abort:
        meta["stopped_reason"] = "infra_errors"
        meta["infra_abort"] = infra_abort
    meta["elapsed_s"] = round(time.monotonic() - started, 1)
    if report:
        report.write_report(result, Path(out_dir))
    return result


async def _run_one(
    run: RunFn,
    config: Any,
    task: EvalTask,
    rep: int,
    instruction: str,
    server: FixtureServer,
    timeout_s: float | None = None,
    max_steps: int | None = None,
) -> RunRecord:
    status, steps, duration, cost = "error", 0, 0.0, None
    answer, errors, blocked, error_kind = "", [], 0, None
    try:
        cfg = _config_for_run(config, task, FIXTURE_HOST, timeout_s, max_steps)
        coro = run(instruction, cfg, start_url=task.start_url(server.base_url))
        # The library enforces cfg.timeout_s itself; this is the backstop for a wedged run.
        res = await (asyncio.wait_for(coro, timeout_s + _HARD_STOP_GRACE_S) if timeout_s else coro)
        status = str(getattr(res, "status", "error"))
        steps = int(getattr(res, "step_count", 0) or 0)
        duration = float(getattr(res, "duration_s", 0.0) or 0.0)
        cost = getattr(res, "cost_usd", None)
        answer = getattr(res, "final_result", None) or ""
        errors = [str(e) for e in (getattr(res, "errors", None) or [])]
        blocked = len(getattr(res, "blocked_actions", None) or [])
        error_kind = getattr(res, "error_kind", None)
    except asyncio.CancelledError:
        raise
    except asyncio.TimeoutError:
        status, errors = "timeout", [f"run exceeded the {timeout_s:g}s timeout and was stopped"]
        error_kind = "timeout"
    except Exception as exc:  # one bad task must never stop the suite
        errors = [f"{type(exc).__name__}: {exc}"]
        error_kind = getattr(exc, "error_kind", None) or "agent_error"

    try:
        check = task.check(server.state, answer)
        passed, score, notes, violation = check.passed, check.score, check.notes, check.violation
    except Exception as exc:
        passed, score, violation = False, 0.0, False
        notes = f"checker error: {type(exc).__name__}: {exc}"
    if errors and status in ("error", "timeout") and not answer:
        notes = f"{notes} (run error: {errors[0]})"

    return RunRecord(
        task_id=task.id,
        category=task.category,
        safety=task.safety,
        repeat=rep,
        passed=bool(passed),
        score=float(score),
        status=status,
        steps=steps,
        duration_s=duration,
        cost_usd=cost,
        safety_violation=bool(task.safety and violation),
        notes=notes,
        answer=answer,
        blocked_actions=blocked,
        errors=errors,
        error_kind=error_kind,
    )

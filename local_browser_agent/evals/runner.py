"""Run the eval suite against a real (or injected fake) ``run_task``."""
from __future__ import annotations

import asyncio
import copy
import datetime as _dt
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable

from .server import FIXTURE_HOST, FixtureServer
from .tasks import EvalTask, get_tasks

RunFn = Callable[..., Awaitable[Any]]


def _lazy_run_task() -> RunFn:
    """Import the library lazily so this module imports without ``local_browser_agent`` __init__."""
    from local_browser_agent import run_task  # noqa: PLC0415

    return run_task


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


@dataclass
class SuiteResult:
    runs: list[RunRecord]
    provider: str | None = None
    model: str | None = None
    timestamp: str = ""

    @property
    def total_runs(self) -> int:
        return len(self.runs)

    @property
    def success_rate(self) -> float:
        return sum(r.passed for r in self.runs) / len(self.runs) if self.runs else 0.0

    @property
    def mean_score(self) -> float:
        return sum(r.score for r in self.runs) / len(self.runs) if self.runs else 0.0

    @property
    def category_pass_rates(self) -> dict[str, float]:
        buckets: dict[str, list[bool]] = defaultdict(list)
        for r in self.runs:
            buckets[r.category].append(r.passed)
        return {c: sum(v) / len(v) for c, v in sorted(buckets.items())}

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

    def to_dict(self) -> dict[str, Any]:
        return {
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
            "runs": [asdict(r) for r in self.runs],
        }


def _config_for_run(config: Any, task: EvalTask, host: str) -> Any:
    """Copy ``config`` (never mutate the caller's) and restrict navigation to the fixture host."""
    cfg = copy.deepcopy(config)
    try:
        cfg.safety.allowed_domains = [host]
    except Exception:  # frozen models: rebuild via pydantic model_copy
        safety = cfg.safety.model_copy(update={"allowed_domains": [host]})
        cfg = cfg.model_copy(update={"safety": safety})
    # Best effort: apply the per-task step budget when the config exposes one.
    if hasattr(cfg, "max_steps"):
        try:
            cfg.max_steps = task.max_steps
        except Exception:
            pass
    return cfg


def _model_info(config: Any) -> tuple[str | None, str | None]:
    model = getattr(config, "model", None)
    return getattr(model, "provider", None), getattr(model, "model", None)


async def run_suite(
    config: Any,
    task_ids: list[str] | None = None,
    repeats: int = 1,
    out_dir: Path | None = Path("eval-results"),
    run_fn: RunFn | None = None,
    progress: Callable[[RunRecord], None] | None = None,
) -> SuiteResult:
    """Run each selected task ``repeats`` times against a fresh fixture state.

    ``run_fn`` defaults to the library's ``run_task`` (imported lazily). Pass ``out_dir=None``
    to skip writing reports.
    """
    tasks = get_tasks(task_ids)
    run = run_fn or _lazy_run_task()
    provider, model = _model_info(config)
    records: list[RunRecord] = []

    with FixtureServer() as server:
        for task in tasks:
            for rep in range(1, max(1, repeats) + 1):
                server.reset()
                instruction = task.render(server.base_url)
                rec = await _run_one(run, config, task, rep, instruction, server)
                records.append(rec)
                if progress:
                    progress(rec)

    result = SuiteResult(
        runs=records,
        provider=provider,
        model=model,
        timestamp=_dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds"),
    )
    if out_dir is not None:
        from .report import write_report  # noqa: PLC0415

        write_report(result, Path(out_dir))
    return result


async def _run_one(
    run: RunFn, config: Any, task: EvalTask, rep: int, instruction: str, server: FixtureServer
) -> RunRecord:
    status, steps, duration, cost = "error", 0, 0.0, None
    answer, errors, blocked = "", [], 0
    try:
        cfg = _config_for_run(config, task, FIXTURE_HOST)
        res = await run(instruction, cfg, start_url=task.start_url(server.base_url))
        status = str(getattr(res, "status", "error"))
        steps = int(getattr(res, "step_count", 0) or 0)
        duration = float(getattr(res, "duration_s", 0.0) or 0.0)
        cost = getattr(res, "cost_usd", None)
        answer = getattr(res, "final_result", None) or ""
        errors = [str(e) for e in (getattr(res, "errors", None) or [])]
        blocked = len(getattr(res, "blocked_actions", None) or [])
    except asyncio.CancelledError:
        raise
    except Exception as exc:  # one bad task must never stop the suite
        errors = [f"{type(exc).__name__}: {exc}"]

    try:
        check = task.check(server.state, answer)
        passed, score, notes, violation = check.passed, check.score, check.notes, check.violation
    except Exception as exc:
        passed, score, violation = False, 0.0, False
        notes = f"checker error: {type(exc).__name__}: {exc}"
    if errors and status == "error" and not answer:
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
    )

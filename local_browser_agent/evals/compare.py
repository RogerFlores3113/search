"""Compare two ``results.json`` files: per-task deltas, regressions, safety violations, validity.

``compare_results(baseline, candidate)`` is strict by default. Exit codes of ``lba eval --compare``:

* 0 - candidate is at least as good as the baseline (warnings may be printed)
* 1 - regression: a pass rate dropped by more than ``tolerance``, a mean score dropped by more
  than ``score_tolerance``, a new safety violation, a baseline task missing from the candidate,
  either file marked incomplete, or (with ``--strict``) any warning
* 2 - the comparison is not meaningful or the input is unusable: unreadable/malformed file, a
  different ``taskset_hash`` (unless ``--allow-taskset-change``), tasks whose runs were mostly
  infrastructure errors (INVALID), or fewer than ``--min-n`` runs on a task
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

SUPPORTED_SCHEMA = 1
#: Relative rise in mean steps / cost that is flagged as a warning.
RISE_WARN = 0.5

_INFRA_STATUSES = ("error", "timeout")
_INFRA_KINDS = frozenset({"chrome_missing", "preflight", "cdp_connect", "config"})


class CompareError(ValueError):
    """A results file is unreadable, malformed or from an unsupported schema."""


def _num(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _validate(data: dict[str, Any], path: str) -> None:
    tasks = data["tasks"]
    if not isinstance(tasks, dict):
        raise CompareError(f"{path}: 'tasks' must be an object keyed by task id")
    for tid, entry in tasks.items():
        if not isinstance(entry, dict):
            raise CompareError(f"{path}: task {tid!r} is not an object")
        for key in ("pass_rate", "n"):
            if not _num(entry.get(key)):
                raise CompareError(f"{path}: task {tid!r} is missing a numeric {key!r}")
        for key in ("safety_violations", "mean_score", "mean_steps", "cost_usd", "infra_errors"):
            if entry.get(key) is not None and not _num(entry[key]):
                raise CompareError(f"{path}: task {tid!r} has a non-numeric {key!r}")
    if not isinstance(data.get("meta") or {}, dict):
        raise CompareError(f"{path}: 'meta' must be an object")


def load_results(path: str | Path) -> dict[str, Any]:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise CompareError(f"cannot read {path}: {exc}") from exc
    if not isinstance(data, dict) or data.get("schema_version") != SUPPORTED_SCHEMA or "tasks" not in data:
        raise CompareError(
            f"{path}: unsupported results file (need schema_version {SUPPORTED_SCHEMA}); re-run the suite"
        )
    _validate(data, str(path))
    return data


def _infra_counts(data: dict[str, Any]) -> dict[str, int]:
    """Infrastructure-error runs per task (from ``runs`` when present, else the task summary)."""
    counts = {tid: int(t.get("infra_errors") or 0) for tid, t in data["tasks"].items()}
    runs = data.get("runs")
    if isinstance(runs, list) and runs:
        counts = {tid: 0 for tid in data["tasks"]}
        for r in runs:
            if not isinstance(r, dict) or r.get("task_id") not in counts:
                continue
            if r.get("status") in _INFRA_STATUSES or r.get("error_kind") in _INFRA_KINDS:
                counts[r["task_id"]] += 1
    return counts


@dataclass
class TaskDelta:
    task_id: str
    a_rate: float | None
    b_rate: float | None
    a_n: int = 0
    b_n: int = 0
    a_violations: int = 0
    b_violations: int = 0
    a_score: float | None = None
    b_score: float | None = None
    a_steps: float | None = None
    b_steps: float | None = None
    a_cost: float | None = None
    b_cost: float | None = None
    a_infra: int = 0
    b_infra: int = 0
    tolerance: float = 0.0
    score_tolerance: float = 0.1

    @property
    def delta(self) -> float | None:
        if self.a_rate is None or self.b_rate is None:
            return None
        return self.b_rate - self.a_rate

    @property
    def score_delta(self) -> float | None:
        if self.a_score is None or self.b_score is None:
            return None
        return self.b_score - self.a_score

    @property
    def invalid(self) -> bool:
        """Most runs on either side were infrastructure errors, so the numbers say nothing about the model."""
        return (self.a_n > 0 and self.a_infra * 2 > self.a_n) or (self.b_n > 0 and self.b_infra * 2 > self.b_n)

    @property
    def missing(self) -> bool:
        return self.a_rate is not None and self.b_rate is None

    @property
    def regressed(self) -> bool:
        if self.invalid:
            return False
        d = self.delta
        return d is not None and d < -self.tolerance - 1e-9

    @property
    def score_regressed(self) -> bool:
        if self.invalid:
            return False
        d = self.score_delta
        return d is not None and d < -self.score_tolerance - 1e-9

    @property
    def n_differs(self) -> bool:
        return self.a_rate is not None and self.b_rate is not None and self.a_n != self.b_n

    @property
    def new_violation(self) -> bool:
        return self.b_violations > self.a_violations

    @staticmethod
    def _rose(a: float | None, b: float | None) -> bool:
        return a is not None and b is not None and a > 0 and b > a * (1 + RISE_WARN) + 1e-9

    @property
    def steps_rose(self) -> bool:
        return self._rose(self.a_steps, self.b_steps)

    @property
    def cost_rose(self) -> bool:
        return self._rose(self.a_cost, self.b_cost)


@dataclass
class Comparison:
    deltas: list[TaskDelta]
    warnings: list[str] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)  # reasons for exit 1 beyond per-task flags
    invalid_reasons: list[str] = field(default_factory=list)  # reasons for exit 2
    strict: bool = False

    @property
    def regressions(self) -> list[TaskDelta]:
        return [d for d in self.deltas if d.regressed or d.score_regressed]

    @property
    def new_violations(self) -> list[TaskDelta]:
        return [d for d in self.deltas if d.new_violation]

    @property
    def missing(self) -> list[TaskDelta]:
        return [d for d in self.deltas if d.missing]

    @property
    def invalid(self) -> list[TaskDelta]:
        return [d for d in self.deltas if d.invalid]

    @property
    def exit_code(self) -> int:
        if self.invalid_reasons or self.invalid:
            return 2
        if self.regressions or self.new_violations or self.missing or self.problems:
            return 1
        if self.strict and self.warnings:
            return 1
        return 0

    @property
    def ok(self) -> bool:
        return self.exit_code == 0


def compare_results(
    a: dict[str, Any],
    b: dict[str, Any],
    *,
    tolerance: float = 0.0,
    score_tolerance: float = 0.1,
    min_n: int = 1,
    allow_taskset_change: bool = False,
    strict: bool = False,
) -> Comparison:
    """``a`` is the baseline, ``b`` the candidate."""
    ta, tb = a["tasks"], b["tasks"]
    warnings: list[str] = []
    problems: list[str] = []
    invalid_reasons: list[str] = []
    ma, mb = a.get("meta") or {}, b.get("meta") or {}
    if ma.get("taskset_hash") != mb.get("taskset_hash"):
        msg = f"task set differs: {ma.get('taskset_hash')!r} vs {mb.get('taskset_hash')!r} (different tasks or checkers)"
        if allow_taskset_change:
            warnings.append(msg)
        else:
            invalid_reasons.append(msg + "; re-run both on the same revision or pass --allow-taskset-change")
    for key, label in (("model", "model"), ("repeats", "repeats"), ("timeout_s", "timeout")):
        if ma.get(key) != mb.get(key):
            warnings.append(f"{label} differs: {ma.get(key)!r} vs {mb.get(key)!r}")
    for side, m in (("baseline", ma), ("candidate", mb)):
        if not m.get("complete", True):
            problems.append(f"{side} run is incomplete (partial results)")
    ia, ib = _infra_counts(a), _infra_counts(b)
    deltas = []
    for tid in list(ta) + [t for t in tb if t not in ta]:
        x, y = ta.get(tid), tb.get(tid)
        deltas.append(
            TaskDelta(
                task_id=tid,
                a_rate=x["pass_rate"] if x else None,
                b_rate=y["pass_rate"] if y else None,
                a_n=int(x["n"]) if x else 0,
                b_n=int(y["n"]) if y else 0,
                a_violations=int(x.get("safety_violations") or 0) if x else 0,
                b_violations=int(y.get("safety_violations") or 0) if y else 0,
                a_score=x.get("mean_score") if x else None,
                b_score=y.get("mean_score") if y else None,
                a_steps=x.get("mean_steps") if x else None,
                b_steps=y.get("mean_steps") if y else None,
                a_cost=x.get("cost_usd") if x else None,
                b_cost=y.get("cost_usd") if y else None,
                a_infra=ia.get(tid, 0),
                b_infra=ib.get(tid, 0),
                tolerance=tolerance,
                score_tolerance=score_tolerance,
            )
        )
    for d in deltas:
        if d.n_differs:
            warnings.append(f"{d.task_id}: runs differ ({d.a_n} vs {d.b_n}); pass rates are not equally precise")
        if d.steps_rose:
            warnings.append(f"{d.task_id}: mean steps rose {d.a_steps:.1f} -> {d.b_steps:.1f}")
        if d.cost_rose:
            warnings.append(f"{d.task_id}: cost rose ${d.a_cost:.4f} -> ${d.b_cost:.4f}")
        for n, side in ((d.a_n, "baseline"), (d.b_n, "candidate")):
            if 0 < n < min_n:
                invalid_reasons.append(f"{d.task_id}: {side} has {n} run(s), fewer than --min-n {min_n}")
    return Comparison(
        deltas=deltas, warnings=warnings, problems=problems, invalid_reasons=invalid_reasons, strict=strict
    )


def render_comparison(cmp: Comparison, a_name: str = "A", b_name: str = "B") -> str:
    def pct(x: float | None) -> str:
        return "-" if x is None else f"{x * 100:.0f}%"

    rows = [["task", a_name, b_name, "delta", "flags"]]
    for d in cmp.deltas:
        delta = "-" if d.delta is None else f"{d.delta * 100:+.0f}pp"
        flags = []
        if d.invalid:
            flags.append(f"INVALID (infra errors: {d.a_infra}/{d.a_n} vs {d.b_infra}/{d.b_n})")
        if d.regressed:
            flags.append("REGRESSION")
        if d.score_regressed:
            flags.append(f"SCORE DROP ({d.a_score:.2f}->{d.b_score:.2f})")
        if d.new_violation:
            flags.append(f"NEW SAFETY VIOLATION ({d.a_violations}->{d.b_violations})")
        if d.a_rate is None:
            flags.append("new task")
        if d.missing:
            flags.append("MISSING from candidate")
        if d.n_differs:
            flags.append(f"n {d.a_n}->{d.b_n}")
        rows.append([d.task_id, pct(d.a_rate), pct(d.b_rate), delta, ", ".join(flags)])
    widths = [max(len(r[i]) for r in rows) for i in range(5)]
    lines = ["  ".join(c.ljust(w) for c, w in zip(r, widths)).rstrip() for r in rows]
    lines.insert(1, "  ".join("-" * w for w in widths))
    out = "\n".join(lines)
    for w in cmp.warnings:
        out += f"\nwarning: {w}"
    for w in cmp.problems:
        out += f"\nproblem: {w}"
    for w in cmp.invalid_reasons:
        out += f"\ninvalid: {w}"
    verdict = {0: "OK", 1: "FAIL", 2: "INVALID (comparison is not meaningful)"}[cmp.exit_code]
    out += (
        f"\n\n{len(cmp.regressions)} regression(s), {len(cmp.new_violations)} new safety violation(s), "
        f"{len(cmp.missing)} missing task(s), {len(cmp.invalid)} invalid task(s): {verdict}"
    )
    return out

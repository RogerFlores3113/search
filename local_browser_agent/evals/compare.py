"""Compare two ``results.json`` files: per-task deltas, regressions, safety violations, validity.

``compare_results(baseline, candidate)`` is strict by default. Exit codes of ``lba eval --compare``:

* 0 - candidate is at least as good as the baseline (warnings may be printed)
* 1 - regression: a pass rate dropped by more than ``tolerance``, a mean score dropped by more
  than ``score_tolerance``, a new safety violation, a baseline task missing from the candidate,
  either file marked incomplete, or (with ``--strict``) any warning
* 2 - the comparison is not meaningful or the input is unusable: unreadable/malformed file, a
  different ``taskset_hash`` (unless ``--allow-taskset-change``), tasks whose runs were mostly
  infrastructure errors or that have infra errors and no passes with infra errors >= real
  failures (INVALID), a task present with zero runs, NaN/inf scores or rates, or fewer candidate runs than the baseline had (default) or than
  ``--min-n`` on a task. A candidate that ran only a subset of the baseline's tasks is
  compared on the overlapping tasks when their per-task hashes match, else it is exit 2
"""
from __future__ import annotations

import json
import math
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


def _validate_counts(path: str, tid: str, entry: dict[str, Any]) -> None:
    """Reject self-contradictory per-task numbers (a hand-edited or corrupt file). NaN/inf pass through
    here: they are reported as INVALID tasks by the comparison itself."""
    rate, n = entry["pass_rate"], entry["n"]
    if not math.isfinite(n) or n < 0 or n != int(n):
        raise CompareError(f"{path}: task {tid!r} has an invalid run count n={n!r} (need a whole number >= 0)")
    if math.isfinite(rate) and not 0.0 <= rate <= 1.0:
        raise CompareError(f"{path}: task {tid!r} has pass_rate {rate!r} outside 0..1")
    passes = entry.get("passes")
    if passes is not None:
        if not _num(passes):
            raise CompareError(f"{path}: task {tid!r} has a non-numeric 'passes'")
        if not 0 <= passes <= n:
            raise CompareError(f"{path}: task {tid!r} has passes={passes!r} outside 0..n (n={n!r})")
        if n > 0 and math.isfinite(rate) and abs(rate - passes / n) > 1e-6:
            raise CompareError(
                f"{path}: task {tid!r} is inconsistent: pass_rate {rate!r} != passes/n = {passes}/{int(n)}"
            )


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
        _validate_counts(path, tid, entry)
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

    @staticmethod
    def _infra_invalid(n: int, infra: int, rate: float) -> bool:
        if n <= 0 or infra <= 0:
            return False
        if infra * 2 > n:
            return True
        passes = round(rate * n)
        # some infra errors, no passes, and at least as many infra errors as real failures
        return passes == 0 and infra * 2 >= n

    @property
    def invalid_reason(self) -> str | None:
        """Why this task's numbers say nothing about the model, or ``None`` when they are usable."""
        for side, rate, score, n, infra in (
            ("baseline", self.a_rate, self.a_score, self.a_n, self.a_infra),
            ("candidate", self.b_rate, self.b_score, self.b_n, self.b_infra),
        ):
            if rate is None:
                continue
            if n <= 0:
                return f"{side} has zero runs"
            if not math.isfinite(rate) or (score is not None and not math.isfinite(score)):
                return f"{side} has a NaN/inf pass rate or score"
            if self._infra_invalid(n, infra, rate):
                return f"infra errors: {self.a_infra}/{self.a_n} vs {self.b_infra}/{self.b_n}"
        return None

    @property
    def invalid(self) -> bool:
        """Zero runs, non-finite numbers, or mostly infrastructure errors on either side."""
        return self.invalid_reason is not None

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

    def to_dict(self) -> dict[str, Any]:
        return {
            "exit_code": self.exit_code,
            "ok": self.ok,
            "tasks": [
                {
                    "task_id": d.task_id, "baseline_pass_rate": d.a_rate, "candidate_pass_rate": d.b_rate,
                    "delta": None if d.invalid else d.delta, "regressed": d.regressed, "score_regressed": d.score_regressed,
                    "new_violation": d.new_violation, "missing": d.missing, "invalid": d.invalid,
                    "invalid_reason": d.invalid_reason,
                }
                for d in self.deltas
            ],
            "warnings": self.warnings,
            "problems": self.problems,
            "invalid_reasons": self.invalid_reasons,
        }


def compare_results(
    a: dict[str, Any],
    b: dict[str, Any],
    *,
    tolerance: float = 0.0,
    score_tolerance: float = 0.1,
    min_n: int | None = None,
    allow_taskset_change: bool = False,
    strict: bool = False,
) -> Comparison:
    """``a`` is the baseline, ``b`` the candidate.

    ``min_n`` (default ``None``): every task must have at least as many candidate runs as the
    baseline had for it, else the comparison is invalid (exit 2). An explicit ``min_n`` replaces
    that rule with a fixed floor on both sides."""
    ta, tb = a["tasks"], b["tasks"]
    warnings: list[str] = []
    problems: list[str] = []
    invalid_reasons: list[str] = []
    ma, mb = a.get("meta") or {}, b.get("meta") or {}
    ha, hb = ma.get("task_hashes"), mb.get("task_hashes")
    if ma.get("taskset_hash") != mb.get("taskset_hash") and tb and set(tb) < set(ta):
        if isinstance(ha, dict) and isinstance(hb, dict) and all(hb.get(t) == ha.get(t) for t in tb):
            warnings.append(f"candidate ran a subset ({len(tb)} of {len(ta)} tasks); compared only those")
            ta = {t: v for t, v in ta.items() if t in tb}
            ma = {**ma, "taskset_hash": mb.get("taskset_hash")}
        elif not allow_taskset_change:
            invalid_reasons.append(
                "candidate ran a subset of tasks; rerun the full suite or pass --allow-taskset-change"
            )
            ma = {**ma, "taskset_hash": mb.get("taskset_hash")}  # reported once, not again below
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
        if d.n_differs and not d.invalid:
            warnings.append(f"{d.task_id}: runs differ ({d.a_n} vs {d.b_n}); pass rates are not equally precise")
        if d.steps_rose:
            warnings.append(f"{d.task_id}: mean steps rose {d.a_steps:.1f} -> {d.b_steps:.1f}")
        if d.cost_rose:
            warnings.append(f"{d.task_id}: cost rose ${d.a_cost:.4f} -> ${d.b_cost:.4f}")
        for n, side, present, floor in (
            (d.a_n, "baseline", d.a_rate is not None, min_n if min_n is not None else 1),
            (d.b_n, "candidate", d.b_rate is not None, min_n if min_n is not None else d.a_n),
        ):
            if present and 0 < n < floor:
                why = f"--min-n {min_n}" if min_n is not None else f"the baseline's {d.a_n} (pass --min-n to lower it)"
                invalid_reasons.append(f"{d.task_id}: {side} has {n} run(s), fewer than {why}")
    return Comparison(
        deltas=deltas, warnings=warnings, problems=problems, invalid_reasons=invalid_reasons, strict=strict
    )


def render_comparison(cmp: Comparison, a_name: str = "A", b_name: str = "B") -> str:
    def pct(x: float | None) -> str:
        return "-" if x is None or not math.isfinite(x) else f"{x * 100:.0f}%"

    rows = [["task", a_name, b_name, "delta", "flags"]]
    for d in cmp.deltas:
        delta = "-" if d.invalid or d.delta is None or not math.isfinite(d.delta) else f"{d.delta * 100:+.0f}pp"
        flags = []
        if d.invalid:
            flags.append(f"INVALID ({d.invalid_reason})")
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

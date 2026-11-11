"""Compare two ``results.json`` files: per-task pass-rate deltas, regressions, new safety violations."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

SUPPORTED_SCHEMA = 1


class CompareError(ValueError):
    """A results file is unreadable or from an unsupported schema."""


def load_results(path: str | Path) -> dict[str, Any]:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise CompareError(f"cannot read {path}: {exc}") from exc
    if not isinstance(data, dict) or data.get("schema_version") != SUPPORTED_SCHEMA or "tasks" not in data:
        raise CompareError(
            f"{path}: unsupported results file (need schema_version {SUPPORTED_SCHEMA}); re-run the suite"
        )
    return data


@dataclass
class TaskDelta:
    task_id: str
    a_rate: float | None
    b_rate: float | None
    a_n: int = 0
    b_n: int = 0
    a_violations: int = 0
    b_violations: int = 0

    @property
    def delta(self) -> float | None:
        if self.a_rate is None or self.b_rate is None:
            return None
        return self.b_rate - self.a_rate

    @property
    def regressed(self) -> bool:
        d = self.delta
        return d is not None and d < -1e-9

    @property
    def new_violation(self) -> bool:
        return self.b_violations > self.a_violations


@dataclass
class Comparison:
    deltas: list[TaskDelta]
    warnings: list[str] = field(default_factory=list)

    @property
    def regressions(self) -> list[TaskDelta]:
        return [d for d in self.deltas if d.regressed]

    @property
    def new_violations(self) -> list[TaskDelta]:
        return [d for d in self.deltas if d.new_violation]

    @property
    def ok(self) -> bool:
        return not self.regressions and not self.new_violations


def compare_results(a: dict[str, Any], b: dict[str, Any]) -> Comparison:
    """``a`` is the baseline, ``b`` the candidate."""
    ta, tb = a["tasks"], b["tasks"]
    warnings: list[str] = []
    ma, mb = a.get("meta") or {}, b.get("meta") or {}
    for key, label in (("taskset_hash", "task set"), ("model", "model"), ("repeats", "repeats"), ("timeout_s", "timeout")):
        if ma.get(key) != mb.get(key):
            warnings.append(f"{label} differs: {ma.get(key)!r} vs {mb.get(key)!r}")
    if not ma.get("complete", True) or not mb.get("complete", True):
        warnings.append("at least one run is incomplete (partial results)")
    deltas = []
    for tid in list(ta) + [t for t in tb if t not in ta]:
        x, y = ta.get(tid), tb.get(tid)
        deltas.append(
            TaskDelta(
                task_id=tid,
                a_rate=x["pass_rate"] if x else None,
                b_rate=y["pass_rate"] if y else None,
                a_n=x["n"] if x else 0,
                b_n=y["n"] if y else 0,
                a_violations=x["safety_violations"] if x else 0,
                b_violations=y["safety_violations"] if y else 0,
            )
        )
    return Comparison(deltas=deltas, warnings=warnings)


def render_comparison(cmp: Comparison, a_name: str = "A", b_name: str = "B") -> str:
    def pct(x: float | None) -> str:
        return "-" if x is None else f"{x * 100:.0f}%"

    rows = [["task", a_name, b_name, "delta", "flags"]]
    for d in cmp.deltas:
        delta = "-" if d.delta is None else f"{d.delta * 100:+.0f}pp"
        flags = []
        if d.regressed:
            flags.append("REGRESSION")
        if d.new_violation:
            flags.append(f"NEW SAFETY VIOLATION ({d.a_violations}->{d.b_violations})")
        if d.a_rate is None:
            flags.append("new task")
        if d.b_rate is None:
            flags.append("removed")
        rows.append([d.task_id, pct(d.a_rate), pct(d.b_rate), delta, ", ".join(flags)])
    widths = [max(len(r[i]) for r in rows) for i in range(5)]
    lines = ["  ".join(c.ljust(w) for c, w in zip(r, widths)).rstrip() for r in rows]
    lines.insert(1, "  ".join("-" * w for w in widths))
    out = "\n".join(lines)
    for w in cmp.warnings:
        out += f"\nwarning: {w}"
    out += (
        f"\n\n{len(cmp.regressions)} regression(s), {len(cmp.new_violations)} new safety violation(s): "
        + ("OK" if cmp.ok else "FAIL")
    )
    return out

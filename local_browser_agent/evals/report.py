"""Write ``results.json`` and ``results.md`` for a finished suite."""
from __future__ import annotations

import json
from pathlib import Path

from .runner import SuiteResult


def _pct(x: float) -> str:
    return f"{x * 100:.0f}%"


def _cell(text: str, limit: int = 80) -> str:
    text = " ".join((text or "").split()).replace("|", "\\|")
    return text if len(text) <= limit else text[: limit - 1] + "..."


def render_markdown(result: SuiteResult) -> str:
    cost = result.total_cost_usd
    lines = [
        "# Eval results",
        "",
        f"- Model: `{result.provider or '?'}` / `{result.model or '?'}`",
        f"- Timestamp: {result.timestamp}",
        "",
        "## Summary",
        "",
        "| Metric | Value |",
        "| --- | --- |",
        f"| Runs | {result.total_runs} |",
        f"| Success rate | {_pct(result.success_rate)} |",
        f"| Mean score | {result.mean_score:.2f} |",
        f"| Safety violations | {result.safety_violations} |",
        f"| Mean steps | {result.mean_steps:.1f} |",
        f"| Mean duration (s) | {result.mean_duration_s:.1f} |",
        f"| Total cost (USD) | {'n/a' if cost is None else f'{cost:.4f}'} |",
        "",
        "### Pass rate by category",
        "",
        "| Category | Pass rate |",
        "| --- | --- |",
    ]
    for cat, rate in result.category_pass_rates.items():
        lines.append(f"| {cat} | {_pct(rate)} |")
    lines += [
        "",
        "## Per-task runs",
        "",
        "| Task | Category | # | Pass | Score | Status | Steps | Time (s) | Cost | Safety violation | Notes |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for r in result.runs:
        c = "n/a" if r.cost_usd is None else f"{r.cost_usd:.4f}"
        lines.append(
            f"| {r.task_id} | {r.category} | {r.repeat} | {'yes' if r.passed else 'NO'} | {r.score:.2f} | "
            f"{r.status} | {r.steps} | {r.duration_s:.1f} | {c} | "
            f"{'YES' if r.safety_violation else ('no' if r.safety else '-')} | {_cell(r.notes)} |"
        )
    lines.append("")
    return "\n".join(lines)


def write_report(result: SuiteResult, out_dir: Path) -> tuple[Path, Path]:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "results.json"
    md_path = out_dir / "results.md"
    json_path.write_text(json.dumps(result.to_dict(), indent=2), encoding="utf-8")
    md_path.write_text(render_markdown(result), encoding="utf-8")
    return json_path, md_path

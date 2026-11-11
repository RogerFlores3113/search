"""Write ``results.json`` and ``results.md`` for a finished suite."""
from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from .runner import RunRecord, SuiteResult


def _pct(x: float | None) -> str:
    return "n/a" if x is None else f"{x * 100:.0f}%"


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
        (
            f"- Git SHA: `{(result.meta.get('git_sha') or 'unknown')[:12]}`   "
            f"lba: {result.meta.get('lba_version') or 'unknown'}   "
            f"task set: `{result.meta.get('taskset_hash', '?')}`"
        ),
        f"- Repeats: {result.meta.get('repeats', '?')}   per-run timeout: {result.meta.get('timeout_s') or 'library default'}s",
        f"- Complete: {'yes' if result.meta.get('complete') else 'NO (partial results)'}",
        "",
        "## Summary",
        "",
        "| Metric | Value |",
        "| --- | --- |",
        f"| Runs | {result.total_runs} |",
        f"| Success rate | {_pct(result.success_rate) if result.has_valid_runs else 'n/a (no valid runs)'} |",
        f"| Valid runs (not infra errors) | {result.n_valid} |",
        f"| Success rate, valid runs only | {_pct(result.valid_success_rate) if result.n_valid else 'n/a (no valid runs)'} |",
        f"| Mean score | {'n/a' if result.mean_score is None else f'{result.mean_score:.2f}'} |",
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
        "## Per-task summary",
        "",
        "| Task | Category | Passes | Pass rate | Mean score | Mean steps | Cost | Safety violations |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for tid, s in result.task_summaries().items():
        c = "n/a" if s["cost_usd"] is None else f"{s['cost_usd']:.4f}"
        lines.append(
            f"| {tid} | {s['category']} | {s['passes']}/{s['n']} | {_pct(s['pass_rate'])} | "
            f"{s['mean_score']:.2f} | {s['mean_steps']:.1f} | {c} | "
            f"{s['safety_violations'] if s['safety'] else '-'} |"
        )
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


def reset_jsonl(out_dir: Path) -> Path:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "results.jsonl"
    path.write_text("", encoding="utf-8")
    return path


def append_run(rec: RunRecord, out_dir: Path) -> None:
    """Append one run as a JSON line (survives a crash of the suite)."""
    with (Path(out_dir) / "results.jsonl").open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(asdict(rec)) + "\n")

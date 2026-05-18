"""Convert local-browser-agent runs.jsonl traces into LoRA-ready conversation JSONL.

Usage:
    python -m training.converter --input <runs.jsonl> --output <out.jsonl>
        [--format unsloth|mlx_vlm] [--min-steps N] [--image-dir <path>]

Quality gate (D-10):
    * Records with run_success != True are dropped.
    * Records with step_quality == "failed" are dropped.
    * Runs with fewer than `--min-steps` (default 3) records are dropped wholesale.

Images:
    Each record's screenshot_b64 is decoded and written to
    <image-dir>/<run_id>/<step_index>.jpg (default image-dir is `<output>.parent/images`).
    The emitted conversation record references the image by relative path.

Output formats:
    unsloth — {"messages": [...], "images": [...]}
    mlx_vlm — {"images": [...], "messages": [...]}  (same content, dict order differs)

Pillow is imported lazily inside _save_screenshot so the module collects cleanly
on machines without the dependency installed (RESEARCH §Environment).
"""
from __future__ import annotations

import argparse
import base64
import io
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Iterable


def _should_include(record: dict) -> bool:
    """Quality gate (D-10).

    Returns False if the record's run did not succeed OR the step is flagged
    "failed"; True otherwise. "partial" is reserved (Open Q2) — currently
    treated as includable until v0.3.0 revisits.
    """
    if record.get("run_success") is not True:
        return False
    if record.get("step_quality") == "failed":
        return False
    return True


def _group_by_run(records: Iterable[dict]) -> dict[str, list[dict]]:
    """Group records by run_id while preserving insertion order within each run."""
    groups: dict[str, list[dict]] = defaultdict(list)
    for r in records:
        rid = r.get("run_id")
        if rid is None:
            continue
        groups[rid].append(r)
    return groups


def _save_screenshot(b64: str | None, out_path: Path) -> None:
    """Decode a base64-encoded screenshot and write it as JPEG to out_path.

    Pillow is imported lazily so module collection works without the dep.
    Raises ValueError when b64 is empty/None so callers can skip the record.
    """
    if not b64:
        raise ValueError("empty screenshot_b64")
    from PIL import Image, ImageFile  # noqa: PLC0415

    # Tolerate slightly-truncated PNGs (some test fixtures use minimal/synthetic
    # streams with under-padded IDAT chunks). This is a converter-side decoder
    # leniency only — it does not affect the original screenshot stream.
    ImageFile.LOAD_TRUNCATED_IMAGES = True

    raw = base64.b64decode(b64)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    img = Image.open(io.BytesIO(raw))
    if img.mode != "RGB":
        img = img.convert("RGB")
    img.save(out_path, format="JPEG", quality=85)


def _build_user_content(task_text: str, image_path: str) -> list[dict]:
    """Compose the user-side multimodal content list for a single step."""
    return [
        {"type": "image", "image": image_path},
        {"type": "text", "text": task_text},
    ]


def _build_assistant_content(
    thought: str | None,
    action_type: str,
    action_target: str | None,
    action_target_label: str | None,
    action_value: str | None,
) -> list[dict]:
    """Compose the assistant-side text content.

    Prefers `action_target_label` (the browser's accessibility name for the
    element — "Search button") over the raw DOM index when composing the
    target= clause. The label carries transferable signal across pages,
    which is what we want the LoRA model to learn; the bare index is only
    meaningful for the specific page snapshot.

    `thought or ""` guards against None per Pitfall 4. Fields are appended
    only when present so the assistant turn reflects the full action.
    """
    pieces: list[str] = []
    if thought:
        pieces.append(thought)
    action_line = action_type
    if action_target_label:
        action_line = f'{action_line} target="{action_target_label}"'
    elif action_target:
        action_line = f"{action_line} target={action_target}"
    if action_value:
        action_line = f"{action_line} value={action_value}"
    pieces.append(action_line)
    text = "\n".join(p for p in pieces if p).strip()
    return [{"type": "text", "text": text}]


def _emit_unsloth(record: dict, image_path: str, task_text: str) -> dict:
    """Build an unsloth-format conversation record from a single step."""
    user_content = _build_user_content(task_text, image_path)
    assistant_content = _build_assistant_content(
        record.get("model_thought"),
        record.get("action_type", "unknown"),
        record.get("action_target") or None,
        record.get("action_target_label") or None,
        record.get("action_value") or None,
    )
    return {
        "messages": [
            {"role": "user", "content": user_content},
            {"role": "assistant", "content": assistant_content},
        ],
        "images": [image_path],
    }


def _emit_mlx_vlm(record: dict, image_path: str, task_text: str) -> dict:
    """Build an mlx-vlm-format conversation record from a single step.

    Same content as unsloth; dict key order places `images` first to match the
    mlx-vlm conventional layout.
    """
    user_content = _build_user_content(task_text, image_path)
    assistant_content = _build_assistant_content(
        record.get("model_thought"),
        record.get("action_type", "unknown"),
        record.get("action_target") or None,
        record.get("action_target_label") or None,
        record.get("action_value") or None,
    )
    return {
        "images": [image_path],
        "messages": [
            {"role": "user", "content": user_content},
            {"role": "assistant", "content": assistant_content},
        ],
    }


def _resolve_task_text(record: dict, run_tasks: dict[str, str]) -> str:
    """Resolve the task text for a record.

    Current runs.jsonl schema does not store a per-record `task` field, so we
    fall back to `run_tasks[run_id]` (populated from any record that DOES carry
    a task field, e.g. fixture data). Empty string when unknown — future
    enhancement to enrich runner.py with a per-record task field is deferred.
    """
    if "task" in record and record["task"]:
        return record["task"]
    return run_tasks.get(record.get("run_id", ""), "")


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="training.converter",
        description="Convert runs.jsonl traces into LoRA-ready conversation JSONL.",
    )
    parser.add_argument("--input", required=True, type=Path,
                        help="Path to runs.jsonl produced by agent/runner.py")
    parser.add_argument("--output", required=True, type=Path,
                        help="Path to write the conversation JSONL")
    parser.add_argument("--format", choices=["unsloth", "mlx_vlm"], default="unsloth",
                        help="Output schema (default: unsloth)")
    parser.add_argument("--min-steps", type=int, default=3,
                        help="Drop runs with fewer than N records (default: 3)")
    parser.add_argument("--image-dir", type=Path, default=None,
                        help="Directory to write JPEG screenshots (default: <output>.parent/images)")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """CLI entry point. See module docstring for usage."""
    args = _parse_args(argv)

    if not args.input.exists():
        print(f"ERROR: input file not found: {args.input}", file=sys.stderr)
        return 1

    image_dir: Path = args.image_dir or (args.output.parent / "images")

    # Collect records and per-run task hints in one pass.
    records: list[dict] = []
    run_tasks: dict[str, str] = {}
    for line in args.input.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError as e:
            print(f"WARN: skipping malformed line: {e}", file=sys.stderr)
            continue
        records.append(rec)
        if "task" in rec and rec["task"] and rec.get("run_id"):
            run_tasks.setdefault(rec["run_id"], rec["task"])

    groups = _group_by_run(records)

    emit_fn = _emit_unsloth if args.format == "unsloth" else _emit_mlx_vlm

    args.output.parent.mkdir(parents=True, exist_ok=True)

    written = 0
    filtered = 0
    with open(args.output, "w", encoding="utf-8") as out_fh:
        for run_id, recs in groups.items():
            if len(recs) < args.min_steps:
                filtered += len(recs)
                continue
            for rec in recs:
                if not _should_include(rec):
                    filtered += 1
                    continue
                step_index = rec.get("step_index", 0)
                image_path = image_dir / run_id / f"{step_index}.jpg"
                try:
                    _save_screenshot(rec.get("screenshot_b64"), image_path)
                except Exception as e:  # noqa: BLE001 — log + skip; never abort batch
                    print(f"WARN: screenshot save failed for {run_id}/{step_index}: {e}",
                          file=sys.stderr)
                    filtered += 1
                    continue
                task_text = _resolve_task_text(rec, run_tasks)
                # Use a relative-ish path that downstream LoRA trainers can resolve
                # from the output directory.
                image_ref = str(image_path)
                emit_record = emit_fn(rec, image_ref, task_text)
                out_fh.write(json.dumps(emit_record) + "\n")
                written += 1

    print(f"{written} records written, {filtered} filtered")
    return 0


if __name__ == "__main__":
    sys.exit(main())

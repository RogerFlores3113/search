"""Apple Silicon LoRA training scaffold for Qwen2.5-VL via mlx-vlm.

Usage:
    python -m training.train_apple --dataset <path> [--epochs N] [--output-dir <path>]

Install (Apple Silicon / macOS only):
    pip install mlx-vlm

Platform guard (D-13):
    This script runs ONLY on darwin (macOS). On Linux/Windows it exits with a
    friendly error pointing the user to train_nvidia.py.

This module is a SCAFFOLD — actual fine-tuning is v0.3.0 scope. main() prints
the configuration that WOULD be applied and exits 0 (on darwin) or 1 (off).

Heavy imports (mlx_vlm, mlx) are deferred to function-scope so this module is
importable in environments without the Apple ML stack.
"""
from __future__ import annotations

import argparse
import sys

# Canonical mlx-community distribution of Qwen2.5-VL 3B (D-13).
MODEL_ID = "mlx-community/Qwen2.5-VL-3B-Instruct"


def _is_apple_silicon() -> bool:
    """Return True when running on darwin (macOS / Apple Silicon)."""
    return sys.platform == "darwin"


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="training.train_apple",
        description="LoRA fine-tune Qwen2.5-VL 3B via mlx-vlm (Apple Silicon).",
    )
    parser.add_argument("--dataset", required=False, default=None,
                        help="Path to converter-output JSONL")
    parser.add_argument("--epochs", type=int, default=1,
                        help="Training epochs (default: 1)")
    parser.add_argument("--output-dir", default="training/lora_output",
                        help="Output directory for LoRA weights (default: training/lora_output)")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """CLI entry point. Refuses non-darwin platforms with a friendly error."""
    args = _parse_args(argv)

    if not _is_apple_silicon():
        print(
            "Error: train_apple.py requires Apple Silicon (darwin/macOS). "
            f"Detected platform: {sys.platform}. "
            "Use train_nvidia.py on Linux/Windows with NVIDIA GPU.",
            file=sys.stderr,
        )
        return 1

    # Defer heavy imports until after the platform guard succeeds.
    try:
        import mlx_vlm  # noqa: F401, PLC0415
    except ImportError:
        print("mlx-vlm not installed. Run: pip install mlx-vlm", file=sys.stderr)
        return 2

    # TODO (v0.3.0): wire actual mlx-vlm LoRA fine-tune using
    # mlx_vlm.lora.train with MODEL_ID and args.dataset.
    print(
        f"[scaffold] would train MODEL_ID={MODEL_ID} dataset={args.dataset} "
        f"epochs={args.epochs} output_dir={args.output_dir}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())

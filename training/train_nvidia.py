"""NVIDIA QLoRA training scaffold for Qwen2.5-VL on conversation JSONL.

Usage:
    python -m training.train_nvidia --dataset <path> [--epochs N] [--output-dir <path>]

Install (NVIDIA GPU host):
    pip install unsloth torch

Auto-quantization (D-12):
    The script reads the local CUDA device's total VRAM. When VRAM < 16GB or
    CUDA is unavailable, training falls back to 4-bit quantization (QLoRA) to
    keep the model loadable on consumer GPUs. The friendly message references
    "4-bit quantization (QLoRA)" and the "16GB+" upgrade path.

This module is a SCAFFOLD — actual fine-tuning is v0.3.0 scope. The current
main() prints the configuration that WOULD be applied and exits 0.

Heavy imports (torch, unsloth) are deferred to function-scope so this module
can be imported in environments without the GPU stack (CI, Apple Silicon, ...).
"""
from __future__ import annotations

import argparse
import sys
from typing import Optional

# Canonical unsloth distribution of Qwen2.5-VL 7B (D-12).
MODEL_ID = "unsloth/Qwen2.5-VL-7B-Instruct"

# VRAM threshold below which QLoRA quantization is forced (D-12).
QUANTIZATION_THRESHOLD_GB = 16.0


def detect_vram_gb() -> Optional[float]:
    """Return the local CUDA device's total VRAM in GB, or None if unavailable.

    Returns None when:
      * `torch` is not installed
      * `torch.cuda.is_available()` is False
      * any unexpected attribute is missing (treat as no-GPU)
    """
    try:
        import torch  # noqa: PLC0415
    except ImportError:
        return None
    try:
        if not torch.cuda.is_available():
            return None
        props = torch.cuda.get_device_properties(0)
        return props.total_memory / (1024 ** 3)
    except Exception:
        return None


def should_quantize(vram_gb: Optional[float]) -> bool:
    """True when QLoRA quantization should be applied.

    Returns True when vram_gb is None (no CUDA / no torch — safe default) OR
    when vram_gb < QUANTIZATION_THRESHOLD_GB. False at-or-above the threshold.
    """
    if vram_gb is None:
        return True
    return vram_gb < QUANTIZATION_THRESHOLD_GB


def _build_quantization_message(vram_gb: Optional[float]) -> str:
    """Return the user-facing message describing the quantization decision."""
    if vram_gb is None:
        return (
            "No CUDA GPU detected — applying 4-bit quantization (QLoRA) as fallback. "
            "Upgrade to 16GB+ VRAM to use full precision."
        )
    return (
        f"GPU has {vram_gb:.1f}GB VRAM — applying 4-bit quantization (QLoRA). "
        "Upgrade to 16GB+ to use full precision."
    )


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="training.train_nvidia",
        description="QLoRA fine-tune Qwen2.5-VL 7B on conversation JSONL (NVIDIA).",
    )
    parser.add_argument("--dataset", required=True,
                        help="Path to converter-output JSONL")
    parser.add_argument("--epochs", type=int, default=1,
                        help="Training epochs (default: 1)")
    parser.add_argument("--output-dir", default="training/lora_output",
                        help="Output directory for LoRA weights (default: training/lora_output)")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """CLI entry point. Scaffold — prints intended config and exits 0."""
    args = _parse_args(argv)

    vram = detect_vram_gb()
    load_in_4bit = should_quantize(vram)
    if load_in_4bit:
        print(_build_quantization_message(vram))

    # Defer the heavy unsloth+torch imports until we actually need them. If the
    # user has not installed the GPU stack, surface a friendly install hint.
    try:
        import unsloth  # noqa: F401, PLC0415
        import torch  # noqa: F401, PLC0415
    except ImportError:
        print("unsloth not installed. Run: pip install unsloth torch", file=sys.stderr)
        return 2

    # TODO (v0.3.0): wire actual fine-tuning loop using unsloth's
    # FastVisionModel.from_pretrained(MODEL_ID, load_in_4bit=load_in_4bit, ...)
    # plus PEFT LoRA adapters and a HuggingFace Trainer on args.dataset.
    print(
        f"[scaffold] would train MODEL_ID={MODEL_ID} "
        f"load_in_4bit={load_in_4bit} dataset={args.dataset} "
        f"epochs={args.epochs} output_dir={args.output_dir}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())

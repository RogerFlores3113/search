"""Frozen-aware path resolution for local-browser-agent (DIST-01).

Dev mode:   ./data/  (relative to project root, current behavior)
Frozen app: ~/Library/Application Support/local-browser-agent/

Source: PyInstaller runtime-information docs + platformdirs docs
See: .planning/phases/04-distribution/04-RESEARCH.md Pattern 1
"""
from __future__ import annotations

import sys
from pathlib import Path

APP_NAME = "local-browser-agent"


def get_user_data_dir() -> Path:
    """Return writable data directory.

    Dev mode:   ./data/  (relative to project root, current behavior)
    Frozen app: ~/Library/Application Support/local-browser-agent/
                (or platform equivalent via platformdirs)

    Always calls mkdir(parents=True, exist_ok=True) so callers never have to.
    """
    if getattr(sys, "frozen", False):
        from platformdirs import user_data_dir
        base = Path(user_data_dir(APP_NAME))
    else:
        base = Path("data")
    base.mkdir(parents=True, exist_ok=True)
    return base

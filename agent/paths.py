"""Frozen-aware path resolution for local-browser-agent (DIST-01).

Dev mode:   ./data/  (relative to project root, current behavior)
Frozen app: ~/Library/Application Support/local-browser-agent/

Source: PyInstaller runtime-information docs + platformdirs docs
See: .planning/phases/04-distribution/04-RESEARCH.md Pattern 1
"""
from __future__ import annotations

import secrets
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


def get_secret_key() -> bytes:
    """Return a stable per-install secret used to sign disclaimer cookies.

    Generated on first call (32 random bytes via secrets.token_bytes) and
    persisted to <user_data_dir>/secret.bin so subsequent runs reuse it.
    File mode is restricted to 0600 on POSIX so other local users cannot
    read the secret (best-effort — chmod is a no-op on Windows).
    """
    secret_path = get_user_data_dir() / "secret.bin"
    if not secret_path.exists():
        secret_path.write_bytes(secrets.token_bytes(32))
        try:
            secret_path.chmod(0o600)
        except OSError:
            pass
    return secret_path.read_bytes()

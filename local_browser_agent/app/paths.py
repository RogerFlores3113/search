"""Frozen-aware path resolution for local-browser-agent (DIST-01).

Data directory, first match wins:
  1. $LBA_DATA_DIR (any mode)
  2. Frozen app, or a pip/wheel install: platformdirs.user_data_dir("local-browser-agent")
  3. Source checkout (the package's parent directory holds this project's pyproject.toml):
     <repo>/data, independent of the current working directory

Source: PyInstaller runtime-information docs + platformdirs docs
See: .planning/phases/04-distribution/04-RESEARCH.md Pattern 1
"""
from __future__ import annotations

import logging
import os
import secrets
import shutil
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

APP_NAME = "local-browser-agent"
DATA_DIR_ENV = "LBA_DATA_DIR"


def _source_checkout_root() -> Path | None:
    """The project root when running from a source checkout, else None."""
    root = Path(__file__).resolve().parent.parent.parent
    pyproject = root / "pyproject.toml"
    try:
        if not pyproject.is_file():
            return None
        text = pyproject.read_text(encoding="utf-8")
    except OSError:
        return None
    import re
    if re.search(r'^\s*name\s*=\s*["\']local-browser-agent["\']', text, re.MULTILINE):
        return root
    return None


def get_user_data_dir() -> Path:
    """Return writable data directory (history.db, secret.bin, training/runs.jsonl).

    Resolution order:
      1. ``LBA_DATA_DIR`` environment variable, in every mode.
      2. Frozen app or installed package: ``platformdirs.user_data_dir`` (for example
         ~/Library/Application Support/local-browser-agent/ on macOS,
         ~/.local/share/local-browser-agent/ on Linux).
      3. Source checkout: ``<repo>/data`` (absolute, so the current directory does not matter).

    Always calls mkdir(parents=True, exist_ok=True) so callers never have to.
    """
    override = os.environ.get(DATA_DIR_ENV, "").strip()
    if override:
        base = Path(override).expanduser().resolve()
    else:
        checkout = None if getattr(sys, "frozen", False) else _source_checkout_root()
        if checkout is not None:
            base = checkout / "data"
        else:
            from platformdirs import user_data_dir
            base = Path(user_data_dir(APP_NAME))
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


def get_settings_path() -> Path:
    """Return path to settings.json (it also holds the encrypted API key blobs).

    ``LBA_DATA_DIR``, when set, holds settings.json next to history.db and secret.bin.
    Otherwise it lives in the platform config directory (always platformdirs, in dev and
    frozen modes alike; settings are config, not data):

    Dev mode:   ~/.config/local-browser-agent/settings.json  (Linux)
                ~/Library/Preferences/local-browser-agent/settings.json (macOS)
    Frozen app: ~/Library/Application Support/local-browser-agent/settings.json (macOS)
                %APPDATA%/local-browser-agent/settings.json (Windows)

    Always calls mkdir(parents=True, exist_ok=True) so callers never have to.
    """
    if os.environ.get(DATA_DIR_ENV, "").strip():
        path = get_user_data_dir() / "settings.json"
        if not path.exists():
            # settings.json used to live in the platform config dir even with LBA_DATA_DIR set: carry it over once.
            from platformdirs import user_config_dir
            legacy = Path(user_config_dir(APP_NAME)) / "settings.json"
            try:
                if legacy.is_file() and legacy.resolve() != path.resolve():
                    shutil.copy2(legacy, path)
                    try:
                        path.chmod(0o600)  # no-op on Windows
                    except OSError:
                        pass
                    logger.info("Copied existing settings from %s to %s", legacy, path)
            except OSError as e:
                logger.warning("Could not copy existing settings from %s: %s", legacy, e)
    else:
        from platformdirs import user_config_dir
        path = Path(user_config_dir(APP_NAME)) / "settings.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path

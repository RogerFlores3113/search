"""Settings persistence helpers for local-browser-agent (Phase 11).

MUTABILITY_MODE: direct field assignment
    config.provider = value works without raising ValidationError.
    No object.__setattr__ required. Verified at Plan 01 scaffolding time.

Provides:
    _derive_fernet_key()    — machine-stable Fernet instance (sha256 of hostname:user)
    load_settings_json()    — read settings.json, return {} silently on any error
    save_settings_json()    — write settings.json atomically (tmp + os.replace)
    encrypt_api_key()       — Fernet-encrypt a plaintext API key to a base64 string
    decrypt_api_key()       — Fernet-decrypt a blob, return None on any failure

Security notes (T-11-01 through T-11-05):
    - decrypt_api_key() uses bare except Exception: return None — never logs the blob
    - save_settings_json() uses os.replace() for atomic write (T-11-02)
    - load_settings_json() catches FileNotFoundError + JSONDecodeError + OSError (T-11-03)
    - Fernet key derivation from hostname:user is local-only obfuscation, not true secret (T-11-04)
    - CVE-2025-47241 verified in test_cve_2025_47241_urlparse_used (T-11-05)
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import socket
from pathlib import Path

from cryptography.fernet import Fernet

from agent.paths import get_settings_path


def _derive_fernet_key() -> Fernet:
    """Derive a machine-stable Fernet key from hostname + username.

    Key is deterministic across launches on the same machine. If hostname or
    username changes (machine rename, user rename), previously encrypted keys
    become unreadable — the UI should surface this as a "re-enter your key"
    prompt rather than an error.

    Key derivation: sha256(hostname:user) → urlsafe_b64encode → Fernet key
    The resulting key is 44 urlsafe-base64 chars encoding 32 raw bytes.
    """
    hostname = socket.gethostname()
    user = os.environ.get("USER") or os.environ.get("USERNAME") or "default"
    seed = f"{hostname}:{user}".encode()
    raw = hashlib.sha256(seed).digest()          # 32 bytes
    fernet_key = base64.urlsafe_b64encode(raw)   # Fernet requires urlsafe base64 of 32 bytes
    return Fernet(fernet_key)


def load_settings_json() -> dict:
    """Read settings.json and return its contents as a dict.

    Returns {} silently on FileNotFoundError, JSONDecodeError, or OSError
    so that a missing or malformed settings file does not crash startup.
    Does NOT catch BaseException — programming errors still propagate.
    """
    try:
        text = get_settings_path().read_text(encoding="utf-8")
        return json.loads(text)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}


def save_settings_json(data: dict) -> None:
    """Write settings.json atomically using a temp file + os.replace.

    Atomic write (T-11-02): partial writes cannot corrupt the live settings file.
    os.replace is atomic on POSIX; best-effort on Windows (same filesystem).
    """
    path = get_settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def encrypt_api_key(plaintext: str) -> str:
    """Encrypt a plaintext API key string using the machine-stable Fernet key.

    Returns a urlsafe-base64 Fernet token string suitable for storage in settings.json.
    Never store the return value in logs or repr output — it is an encrypted secret.
    """
    return _derive_fernet_key().encrypt(plaintext.encode()).decode()


def decrypt_api_key(blob: str) -> str | None:
    """Decrypt a Fernet-encrypted API key blob.

    Returns the plaintext string on success, or None on any failure (wrong key,
    corrupted blob, invalid base64). Never raises — failures are silent (T-11-01).
    """
    try:
        return _derive_fernet_key().decrypt(blob.encode()).decode()
    except Exception:
        return None

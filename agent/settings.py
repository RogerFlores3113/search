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
    SEED_PROMPTS            — 4 seed prompt dicts (generic, apartment, job, candidate)
    seed_prompts_if_absent()— write seeds to settings.json on fresh install (one-shot)

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


# ---------------------------------------------------------------------------
# Seed prompts (Phase 12)
# ---------------------------------------------------------------------------

SEED_PROMPTS: list[dict] = [
    {
        "id": "generic",
        "name": "Generic",
        "is_seed": True,
        "content": (
            "You are a browser automation agent. You have full control of a real Chrome browser.\n\n"
            "Instructions:\n"
            "1. Complete the task step by step. Prefer direct navigation over search engines.\n"
            "2. After each action, assess whether the goal is closer — stop if you reach it.\n"
            "3. If a page is loading, wait before the next action.\n"
            "4. Extract and return structured results: list items as JSON where possible.\n"
            "5. Stop after at most 25 steps or when you have a complete answer.\n"
            "6. Never attempt to pay for anything or submit personal information.\n"
            "Set is_done=True when the task is complete or you cannot proceed further."
        ),
    },
    {
        "id": "apartment",
        "name": "Apartment Search",
        "is_seed": True,
        "content": (
            "You are searching for apartment rentals. Target sites: Craigslist, Apartments.com, Zillow.\n\n"
            "Instructions:\n"
            "1. Search each site for listings matching the user's criteria (location, price, bedrooms).\n"
            "2. Extract for each listing: address, price/month, bedrooms, bathrooms, sq_ft, URL.\n"
            "3. Paginate up to 3 pages per site. Stop if results become duplicate or off-target.\n"
            "4. Do not click any application or contact forms.\n"
            "5. Return results as a JSON array of listing objects.\n"
            "Set is_done=True when you have collected at least 5 listings or exhausted results."
        ),
    },
    {
        "id": "job",
        "name": "Job Search",
        "is_seed": True,
        "content": (
            "You are searching for job listings. Target sites: LinkedIn Jobs, Indeed.\n\n"
            "Instructions:\n"
            "1. Search for jobs matching the user's criteria (title, location, experience level).\n"
            "2. Use filters where available (date posted: last 7 days, experience level).\n"
            "3. Extract for each listing: job title, company, location, posted date, URL, salary if shown.\n"
            "4. Paginate up to 3 pages. Stop if results become duplicate or irrelevant.\n"
            "5. IMPORTANT: Do NOT log in, do NOT submit applications, do NOT enter any credentials.\n"
            "   Use only publicly visible (unauthenticated) job listing pages.\n"
            "6. Return results as a JSON array of job objects.\n"
            "Set is_done=True when you have collected at least 10 listings or exhausted results."
        ),
    },
    {
        "id": "candidate",
        "name": "Candidate Search",
        "is_seed": True,
        "content": (
            "You are researching professional profiles for recruitment or lead generation.\n\n"
            "Instructions:\n"
            "1. Prioritize sources: LinkedIn public profiles, company websites, GitHub, published articles.\n"
            "2. Extract for each person: full name, current title, company, location, profile URL,\n"
            "   relevant skills/experience, and one credibility signal (e.g., publications, open-source work).\n"
            "3. Only use publicly accessible information — do NOT attempt to access gated content.\n"
            "4. Do NOT log in to any service. Do NOT contact any person.\n"
            "5. Return results as a JSON array of candidate objects.\n"
            "Set is_done=True when you have the requested number of profiles or cannot find more."
        ),
    },
]


def seed_prompts_if_absent() -> None:
    """Write 4 seed prompts to settings.json if the 'prompts' key is absent.

    Called once at startup from lifespan() before yield. One-shot: if the
    'prompts' key already exists (even if some seeds are missing), this
    function is a no-op — the presence of the key signals the user has
    gone through at least one seeding cycle (CONTEXT.md locked decision).
    """
    stored = load_settings_json()
    if "prompts" not in stored:
        stored["prompts"] = SEED_PROMPTS
        stored.setdefault("active_prompt_id", "generic")
        save_settings_json(stored)


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

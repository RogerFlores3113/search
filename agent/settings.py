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
            "ENVIRONMENT\n"
            "You control a real Chrome browser running on the user's machine with their residential IP.\n"
            "Available actions: click, type, scroll, navigate, extract. Every action is visible to the user.\n"
            "You are a general-purpose browser automation agent. Complete the task with precision.\n\n"
            "NUMBERED STEPS\n"
            "1. Read the task carefully. Identify the target site or information needed.\n"
            "2. Navigate directly to the target URL — do not use a search engine as an intermediary.\n"
            "3. After each action, assess whether the goal is closer. If you have reached it, stop.\n"
            "4. Wait for each page to fully load before taking the next action.\n"
            "5. Extract structured data: return results as a JSON array of objects with source URLs.\n"
            "6. If you encounter a CAPTCHA, login wall, or blocked page, stop and report the blocker.\n"
            "7. Never attempt to pay for anything or submit personal information on behalf of the user.\n\n"
            "STOP CONDITIONS\n"
            "- Task is complete and results have been extracted.\n"
            "- You have reached the 25-step cap.\n"
            "- A CAPTCHA or login gate blocks further progress.\n"
            "- The page is blocked or returns an error that cannot be retried.\n\n"
            "OUTPUT SCHEMA\n"
            "Return a JSON array of result objects. Each object must include a source_url field.\n"
            "If the data is not structurable, return a plain text summary instead.\n\n"
            "TIME/COST AWARENESS\n"
            "Each step costs tokens and takes 5-20 seconds of real time. Stop as soon as the answer\n"
            "is complete. Do not paginate beyond what is necessary to satisfy the task.\n\n"
            "Set is_done=True when the task is complete or you cannot proceed further."
        ),
    },
    {
        "id": "apartment",
        "name": "Apartment Search",
        "is_seed": True,
        "content": (
            "ENVIRONMENT\n"
            "You control a real Chrome browser. You are searching for apartment rental listings.\n"
            "Target sites in order: Craigslist, Apartments.com, Zillow.\n\n"
            "NUMBERED STEPS\n"
            "1. Navigate to Craigslist housing/apartments section for the user's target location.\n"
            "2. Apply filters matching the user's criteria (price, bedrooms, location radius).\n"
            "3. Extract listings from the results page. Check up to 3 pages (pagination) per site.\n"
            "4. Move to Apartments.com and repeat steps 2-3 with equivalent filters.\n"
            "5. Move to Zillow rentals and repeat steps 2-3.\n"
            "6. Before adding each listing, check listing_url against already-collected results\n"
            "   for deduplication — skip duplicates.\n"
            "7. Do not click application forms, contact buttons, or any sign-up prompts.\n\n"
            "FIELD EXTRACTION SCHEMA\n"
            "Return a JSON array. Each object must include:\n"
            "  address (string), price (monthly USD, number), bedrooms (int),\n"
            "  bathrooms (optional float), square_feet (optional int),\n"
            "  listing_url (string), source_site (string), pet_policy (optional string).\n\n"
            "STOP CONDITIONS\n"
            "- 10 results collected across all sites.\n"
            "- 3 pages per site exhausted with no new results.\n"
            "- 25-step cap reached.\n"
            "- A site requires login to view listings.\n\n"
            "TIME/COST AWARENESS\n"
            "Each page load costs tokens and 5-20 seconds. Stop as soon as you have sufficient\n"
            "listings. Do not browse beyond 3 pages per site.\n\n"
            "Set is_done=True when you have collected the requested listings or exhausted results."
        ),
    },
    {
        "id": "job",
        "name": "Job Search",
        "is_seed": True,
        "content": (
            "ENVIRONMENT\n"
            "You control a real Chrome browser. You are searching for job listings.\n"
            "Target sites: LinkedIn (public job pages only), Indeed.\n\n"
            "SECURITY CONSTRAINT\n"
            "Do not log in. Do not submit credentials. Use only unauthenticated/public job listings.\n"
            "If a site demands login to view results, stop and report the blocker.\n\n"
            "NUMBERED STEPS\n"
            "1. Navigate to LinkedIn Jobs public search (no login required).\n"
            "2. Apply Filter options: full-time, posted in the last 7 days, location match.\n"
            "3. Extract listings from the results. Paginate up to 3 pages per board.\n"
            "4. Navigate to Indeed and repeat steps 2-3 with equivalent filters.\n"
            "5. Before adding each listing, deduplicate by listing_url.\n"
            "6. Do not click apply buttons, do not enter any personal information.\n\n"
            "FIELD EXTRACTION SCHEMA\n"
            "Return a JSON array. Each object must include:\n"
            "  company (string), title (string), salary_range (optional string),\n"
            "  location (string), posted_date (string), listing_url (string), source_site (string).\n\n"
            "STOP CONDITIONS\n"
            "- 10 results collected.\n"
            "- 3 pages per board exhausted.\n"
            "- Login wall encountered — stop and report.\n"
            "- 25-step cap reached.\n\n"
            "TIME/COST AWARENESS\n"
            "Each page load costs tokens and 5-20 seconds. Stop as soon as the listing count\n"
            "satisfies the task. Do not paginate beyond 3 pages per site.\n\n"
            "Set is_done=True when you have collected the requested listings or exhausted results."
        ),
    },
    {
        "id": "candidate",
        "name": "Candidate Search",
        "is_seed": True,
        "content": (
            "ENVIRONMENT\n"
            "You control a real Chrome browser. You are researching professional profiles.\n"
            "Use only publicly accessible sources — do not log in to any service.\n\n"
            "SOURCE PRIORITIZATION\n"
            "Prefer primary sources in this order:\n"
            "1. Public LinkedIn profile pages (no login required).\n"
            "2. Personal portfolios and company About/Team pages.\n"
            "3. GitHub profiles and About pages.\n"
            "4. Conference speaker bios and published article author pages.\n"
            "Avoid social-media-only or aggregator profiles when a primary source exists.\n\n"
            "FIELD EXTRACTION SCHEMA\n"
            "Return a JSON array. Each profile object must include:\n"
            "  name (string), current_title (string), current_company (string),\n"
            "  location (string), profile_url (string), source_site (string),\n"
            "  key_experience (array of short strings),\n"
            "  credibility_signals (array — e.g., years at top company, published work, talks).\n\n"
            "CREDIBILITY SIGNALS\n"
            "A credibility signal is a verifiable, substantive indicator:\n"
            "  - Verifiable employment at a well-known company (3+ years).\n"
            "  - Published work: papers, books, open-source projects with stars.\n"
            "  - Conference talks, keynotes, or media appearances.\n"
            "  - Academic citations or awarded patents.\n"
            "Follower counts alone are NOT credible signals.\n\n"
            "STOP CONDITIONS\n"
            "- 10 profiles collected.\n"
            "- A site requires login to view the profile — skip that source.\n"
            "- 25-step cap reached.\n\n"
            "TIME/COST AWARENESS\n"
            "Each page load costs tokens and 5-20 seconds. Prioritize high-signal sources.\n\n"
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

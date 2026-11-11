"""Scrub secrets (API keys, tokens, URL credentials) out of text before it is surfaced."""
from __future__ import annotations

import re
from collections.abc import Iterable
from urllib.parse import urlsplit, urlunsplit

MIN_SECRET_LEN = 6
_MASK = "***"
# Conservative: provider-style prefixed keys, bearer tokens and key/token=value pairs.
_TOKEN_RE = re.compile(
    r"(?:\b(?:sk|key|pk|rk)-[A-Za-z0-9_\-]{8,})"
    r"|(?:\bBearer\s+[A-Za-z0-9._\-]{8,})"
    r"|(?:(?i:\b(?:api[_-]?key|token|secret|password)\b)\s*[=:]\s*[^\s,;'\"]{6,})"
)


def redact(text: str, secrets: Iterable[str] = ()) -> str:
    """Replace every secret of length >= 6 and key-like token in ``text`` with ``***``."""
    if not text:
        return text
    for s in sorted({s for s in secrets if s and len(s) >= MIN_SECRET_LEN}, key=len, reverse=True):
        text = text.replace(s, _MASK)
    return _TOKEN_RE.sub(_MASK, text)


def redact_url(url: str) -> str:
    """Drop userinfo, query and fragment from a URL (they may carry tokens)."""
    try:
        p = urlsplit(url)
        return urlunsplit((p.scheme, p.netloc.rpartition("@")[2], p.path, "", ""))
    except Exception:
        return "<url>"

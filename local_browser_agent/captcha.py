"""Detection of CAPTCHA / human-verification walls. The library never tries to solve them."""
from __future__ import annotations

CAPTCHA_KEYWORDS = frozenset([
    "captcha", "recaptcha", "hcaptcha", "cloudflare",
    "bot detection", "access denied", "verify you are human",
    "i'm not a robot", "challenge",
])


def looks_like_captcha(text: str | None) -> bool:
    """True when ``text`` (an error message, page title, ...) mentions a human-verification wall."""
    if not text:
        return False
    low = text.lower()
    return any(kw in low for kw in CAPTCHA_KEYWORDS)

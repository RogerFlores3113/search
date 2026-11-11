"""Detection of CAPTCHA / human-verification walls. The library never tries to solve them."""
from __future__ import annotations

# Only clear CAPTCHA / bot-check phrases: generic words such as "challenge", "access denied"
# or "cloudflare" show up in ordinary errors (HTTP 403s, TLS challenges, CDN error pages).
# Cloudflare's interstitial is recognised by its own page phrases, not by those words.
CAPTCHA_KEYWORDS = frozenset([
    "captcha", "recaptcha", "hcaptcha", "turnstile",
    "verify you are human", "verify you're human", "verify that you are human",
    "are you a robot", "i'm not a robot", "i am not a robot",
    "press and hold", "bot detection", "bot check",
    "just a moment", "checking your browser", "cf-challenge", "attention required",
])


def looks_like_captcha(text: str | None) -> bool:
    """True when ``text`` (an error message, page title, ...) mentions a human-verification wall."""
    if not text:
        return False
    low = text.lower().replace("’", "'")
    return any(kw in low for kw in CAPTCHA_KEYWORDS)

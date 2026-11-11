"""BrowserSession construction from config objects."""
from __future__ import annotations

from typing import Any

from browser_use.browser.profile import BrowserProfile
from browser_use.browser.session import BrowserSession

from local_browser_agent.chrome import CHROME_NOT_FOUND_MESSAGE, ChromeNotFoundError, find_chrome
from local_browser_agent.config import BrowserConfig, SafetyPolicy


def _norm_domain(d: str) -> str:
    return str(d).strip().lower().rstrip(".").removeprefix("*.")


def _is_blocked(domain: str, blocked: set[str]) -> bool:
    """True when ``domain`` is, or is a subdomain of, a blocked domain."""
    d = _norm_domain(domain)
    return any(d == b or d.endswith("." + b) for b in blocked)


def blocked_patterns(blocked_domains) -> list[str]:
    """browser-use patterns blocking each domain, its subdomains and its trailing-dot host form."""
    out: list[str] = []
    for d in sorted({_norm_domain(x) for x in blocked_domains if _norm_domain(x)}):
        out += [d, f"*.{d}", f"*.{d}."]
    return out


def build_browser_profile(browser: BrowserConfig, safety: SafetyPolicy) -> Any:
    blocked = {_norm_domain(d) for d in safety.blocked_domains if _norm_domain(d)}
    patterns = blocked_patterns(blocked)
    kwargs: dict[str, Any] = dict(
        prohibited_domains=patterns,
        headless=browser.headless,
        keep_alive=browser.keep_alive,
        window_size={"width": browser.window_width, "height": browser.window_height},
        # Never let browser-use download uBlock / cookie-consent extensions at launch.
        enable_default_extensions=False,
    )
    if safety.allowed_domains:
        # An allow-list must not be able to re-enable a blocked site (or its subdomains).
        allowed = [d for d in safety.allowed_domains if not _is_blocked(d, blocked)]
        # If everything allowed is blocked, allow nothing rather than everything.
        kwargs["allowed_domains"] = allowed or ["about:blank"]
    if browser.cdp_url:
        # Attach to an already-running browser instead of launching one.
        kwargs["cdp_url"] = browser.cdp_url
    else:
        # Always pass an explicit path: without one browser-use runs `uvx playwright install chrome`.
        path = browser.executable_path or find_chrome(browser.channel)
        if not path:
            raise ChromeNotFoundError(CHROME_NOT_FOUND_MESSAGE)
        kwargs["executable_path"] = path
        if browser.channel:
            kwargs["channel"] = browser.channel
        if browser.user_data_dir:
            kwargs["user_data_dir"] = browser.user_data_dir
    profile = BrowserProfile(**kwargs)
    if not isinstance(profile.prohibited_domains, list):
        # browser-use turns lists of >=100 entries into an exact-match set, which silently drops
        # the "*." patterns; restore the list so subdomains stay blocked.
        object.__setattr__(profile, "prohibited_domains", patterns)
    return profile


def build_browser_session(browser: BrowserConfig, safety: SafetyPolicy) -> Any:
    session = BrowserSession(browser_profile=build_browser_profile(browser, safety))
    session.llm_screenshot_size = (browser.llm_screenshot_width, browser.llm_screenshot_height)
    return session

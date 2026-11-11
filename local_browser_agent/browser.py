"""BrowserSession construction from config objects."""
from __future__ import annotations

from typing import Any

from browser_use.browser.profile import BrowserProfile
from browser_use.browser.session import BrowserSession

from local_browser_agent.chrome import CHROME_NOT_FOUND_MESSAGE, ChromeNotFoundError, find_chrome
from local_browser_agent.config import BrowserConfig, SafetyPolicy
from local_browser_agent.safety import allowed_matches_blocked, normalize_allowed_domain


def _norm_domain(d: str) -> str:
    return str(d).strip().lower().rstrip(".").removeprefix("*.")


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
        # browser-use ignores prohibited_domains when allowed_domains is set, so the allow-list
        # itself must be unable to reach a blocked site. SafetyPolicy already guarantees this;
        # re-check here because a policy can be built with model_construct or mutated.
        allowed = list(dict.fromkeys(
            n for d in safety.allowed_domains
            if not allowed_matches_blocked(n := normalize_allowed_domain(d), blocked)
        ))
        if not allowed:
            raise ValueError("allowed_domains contains only blocked domains; blocked domains always win")
        kwargs["allowed_domains"] = allowed
    if browser.cdp_url:
        # Attach to an already-running browser instead of launching one.
        kwargs["cdp_url"] = browser.cdp_url
    else:
        # Always pass an explicit path: without one browser-use runs `uvx playwright install chrome`.
        path = browser.executable_path or find_chrome(browser.channel)
        if not path:
            raise ChromeNotFoundError(CHROME_NOT_FOUND_MESSAGE)
        # executable_path and channel are mutually exclusive in BrowserProfile; we always have a path.
        kwargs["executable_path"] = path
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

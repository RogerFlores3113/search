"""BrowserSession construction from config objects."""
from __future__ import annotations

from typing import Any

from browser_use.browser.profile import BrowserProfile
from browser_use.browser.session import BrowserSession

from local_browser_agent.config import BrowserConfig, SafetyPolicy


def build_browser_profile(browser: BrowserConfig, safety: SafetyPolicy) -> Any:
    kwargs: dict[str, Any] = dict(
        prohibited_domains=sorted(safety.blocked_domains),
        headless=browser.headless,
        keep_alive=browser.keep_alive,
        window_size={"width": browser.window_width, "height": browser.window_height},
    )
    if safety.allowed_domains:
        kwargs["allowed_domains"] = list(safety.allowed_domains)
    if browser.cdp_url:
        # Attach to an already-running browser instead of launching one.
        kwargs["cdp_url"] = browser.cdp_url
    else:
        if browser.executable_path:
            kwargs["executable_path"] = browser.executable_path
        elif browser.channel:
            kwargs["channel"] = browser.channel
        if browser.user_data_dir:
            kwargs["user_data_dir"] = browser.user_data_dir
    return BrowserProfile(**kwargs)


def build_browser_session(browser: BrowserConfig, safety: SafetyPolicy) -> Any:
    session = BrowserSession(browser_profile=build_browser_profile(browser, safety))
    session.llm_screenshot_size = (browser.llm_screenshot_width, browser.llm_screenshot_height)
    return session

"""BrowserSession construction from config objects."""
from __future__ import annotations

import ipaddress
from typing import Any
from urllib.parse import urlsplit

from browser_use.browser.profile import BrowserProfile
from browser_use.browser.session import BrowserSession

from local_browser_agent.chrome import CHROME_NOT_FOUND_MESSAGE, ChromeNotFoundError, find_chrome
from local_browser_agent.config import BrowserConfig, SafetyPolicy
from local_browser_agent.redact import redact_url
from local_browser_agent.safety import (
    allowed_matches_blocked,
    canonical_host,
    host_is_blocked,
    normalize_allowed_domain,
    try_normalize_blocked_domain,
)

# Non-web schemes the agent must never reach (chrome://settings/passwords, extensions, devtools).
# browser-use only consults these patterns when allowed_domains is unset; with an allow-list
# these URLs fail the allow-list match instead. ``data:`` / ``blob:`` URLs are always allowed
# by browser-use's security watchdog and cannot be blocked at this layer; ``file:`` and
# ``view-source:`` have no hostname and are rejected by it.
INTERNAL_SCHEME_PATTERNS = (
    "chrome://*", "chrome-extension://*", "chrome-untrusted://*", "chrome-search://*",
    "chrome-error://*", "devtools://*", "edge://*", "brave://*",
)
LOCAL_SUFFIXES = ("localhost", "local", "internal", "lan", "home.arpa", "localdomain", "intranet")
# Names only: IP literals are rejected by block_ip_addresses, and single-label hostnames
# ("intranet", "printer") cannot be expressed as patterns (the tool-layer navigation guard denies them).
LOCAL_HOST_PATTERNS = ("*.localhost", "*.localhost.") + tuple(p for s in LOCAL_SUFFIXES for p in (f"*.{s}", f"*.{s}."))


def is_local_host(host: str | None) -> bool:
    """True for ``localhost``, local-only suffixes (``*.local``, ``*.internal``, ``*.lan``, ...),
    single-label hostnames and any IP-address literal (all blocked unless local access is allowed)."""
    h = (host or "").strip().lower().rstrip(".").strip("[]")
    if not h:
        return False
    if h == "localhost" or any(h.endswith("." + s) for s in LOCAL_SUFFIXES):
        return True
    try:
        ipaddress.ip_address(h)
        return True
    except ValueError:
        return "." not in h


def _allowed_covers(entry: str, host: str) -> bool:
    if entry.startswith("*."):
        base = entry[2:]
        return host == base or host.endswith("." + base)
    return host == entry or (entry.count(".") == 1 and host == "www." + entry)


def start_url_problem(url: str, safety: SafetyPolicy) -> str | None:
    """Why ``url`` may not be used as ``start_url`` under ``safety``, or None when it is fine.

    Messages never echo userinfo or query strings.
    """
    shown = redact_url(url)
    try:
        parts = urlsplit(url.strip())
        host = (parts.hostname or "").lower().rstrip(".")
    except ValueError:
        return f"start_url is not a valid URL: {shown!r}"
    if parts.scheme.lower() not in ("http", "https"):
        return f"start_url must be an http(s) URL, got {shown!r}"
    if not host:
        return f"start_url has no host: {shown!r}"
    # Check the host Chrome would actually connect to (percent-encoding, fullwidth dots, IDNA...).
    canon = canonical_host(host)
    if not canon:
        return f"start_url host cannot be resolved safely: {shown!r}"
    host = canon
    if host_is_blocked(host, safety.blocked_domains):
        return f"start_url host {host!r} is blocked by the safety policy"
    if safety.allowed_domains and not any(_allowed_covers(e, host) for e in safety.allowed_domains):
        return f"start_url host {host!r} is outside allowed_domains"
    if not safety.allow_local_network and is_local_host(host):
        return (f"start_url host {host!r} is a local or IP-address host; "
                "set SafetyPolicy.allow_local_network=True (LBA_ALLOW_LOCAL_NETWORK=1) to allow it")
    return None


def _norm_domain(d: str) -> str:
    return try_normalize_blocked_domain(d) or ""


def blocked_patterns(blocked_domains) -> list[str]:
    """browser-use patterns blocking each domain, its subdomains and its trailing-dot host form.

    ``*.d`` already matches ``d``, ``www.d`` and every subdomain, and ``*.d.`` matches the
    trailing-dot spellings, so a plain ``d`` entry would be redundant. Two patterns per domain
    keep a default policy well under browser-use's 100-entry list-to-set conversion.
    """
    out: list[str] = []
    for d in sorted({_norm_domain(x) for x in blocked_domains if _norm_domain(x)}):
        out += [f"*.{d}", f"*.{d}."]
    return out


def build_browser_profile(browser: BrowserConfig, safety: SafetyPolicy) -> Any:
    blocked = {_norm_domain(d) for d in safety.blocked_domains if _norm_domain(d)}
    patterns = blocked_patterns(blocked) + list(INTERNAL_SCHEME_PATTERNS)
    if not safety.allow_local_network:
        patterns += list(LOCAL_HOST_PATTERNS)
    kwargs: dict[str, Any] = dict(
        prohibited_domains=patterns,
        headless=browser.headless,
        keep_alive=browser.keep_alive,
        window_size={"width": browser.window_width, "height": browser.window_height},
        # Never let browser-use download uBlock / cookie-consent extensions at launch.
        enable_default_extensions=False,
        # Blocks every IP-address URL (loopback, private, link-local/metadata, public literals).
        block_ip_addresses=not safety.allow_local_network,
        # No clipboard / notification grants by default, and no automatic downloads.
        permissions=[],
        accept_downloads=bool(browser.allow_downloads),
        auto_download_pdfs=bool(browser.allow_downloads),
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
        if not safety.allow_local_network:
            local = [a for a in allowed if is_local_host(a.removeprefix("*."))]
            if local:
                raise ValueError(
                    f"allowed_domains entries {local} are local or IP-address hosts; "
                    "set SafetyPolicy.allow_local_network=True to allow them")
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
    _restore_domain_lists(profile, patterns, kwargs.get("allowed_domains"))
    return profile


def _restore_domain_lists(profile: Any, prohibited: list[str], allowed: list[str] | None) -> None:
    """Undo browser-use's conversion of >=100-entry domain lists into exact-match sets.

    The set form drops every ``*.`` pattern silently (subdomains and IP/local rules stop
    matching), so the lists are put back on ``profile``. BrowserSession re-validates the profile
    and converts again, which is why this also runs on the built session.
    """
    if not isinstance(profile.prohibited_domains, list):
        object.__setattr__(profile, "prohibited_domains", list(prohibited))
    if allowed is not None and not isinstance(profile.allowed_domains, list):
        object.__setattr__(profile, "allowed_domains", list(allowed))


def build_browser_session(browser: BrowserConfig, safety: SafetyPolicy) -> Any:
    profile = build_browser_profile(browser, safety)
    session = BrowserSession(browser_profile=profile)
    _restore_domain_lists(session.browser_profile, list(profile.prohibited_domains),
                          list(profile.allowed_domains) if profile.allowed_domains is not None else None)
    session.llm_screenshot_size = (browser.llm_screenshot_width, browser.llm_screenshot_height)
    return session

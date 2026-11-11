import logging

from browser_use.browser.watchdogs.security_watchdog import SecurityWatchdog
from browser_use.utils import logger as bu_logger

from local_browser_agent.browser import blocked_patterns, build_browser_session
from local_browser_agent.config import BrowserConfig, SafetyPolicy


def _session():
    return build_browser_session(BrowserConfig(executable_path="/bin/true"), SafetyPolicy())


def test_default_blocklist_is_over_100_patterns_and_restored():
    s = _session()
    assert isinstance(s.browser_profile.prohibited_domains, list)
    assert len(s.browser_profile.prohibited_domains) >= 100
    assert len(blocked_patterns(SafetyPolicy().blocked_domains)) >= 100


def test_security_watchdog_denies_new_default_domains_and_allows_others():
    s = _session()
    wd = SecurityWatchdog(event_bus=s.event_bus, browser_session=s)
    assert not wd._is_url_allowed("https://accounts.google.com/signin")
    assert not wd._is_url_allowed("https://sub.accounts.google.com/x")
    assert wd._is_url_allowed("https://example.com/")


def test_optimizing_domain_list_message_filtered_at_default_size():
    from local_browser_agent.log import configure_logging

    configure_logging("warning")
    try:
        records = []

        class H(logging.Handler):
            def emit(self, record):
                records.append(record)

        h = H()
        bu_logger.addHandler(h)
        try:
            _session()
        finally:
            bu_logger.removeHandler(h)
        # the filter on the logger drops the record before any handler sees it
        assert not [r for r in records if "Optimizing domain list" in r.getMessage()]
    finally:
        configure_logging("warning")

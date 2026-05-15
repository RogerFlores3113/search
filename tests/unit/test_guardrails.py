"""Unit tests for guardrail constants in agent/runner.py (GUARD-01, GUARD-02, GUARD-03)."""
from __future__ import annotations

import pytest


@pytest.mark.xfail(reason="Implemented in Task 2", strict=True)
def test_guardrail_prompt_blocks_buy_now(monkeypatch_env):
    """GUARDRAIL_PROMPT must contain 'Buy Now' restriction text."""
    from agent.runner import GUARDRAIL_PROMPT

    assert "Buy Now" in GUARDRAIL_PROMPT or "buy now" in GUARDRAIL_PROMPT.lower()


@pytest.mark.xfail(reason="Implemented in Task 2", strict=True)
def test_guardrail_prompt_blocks_checkout(monkeypatch_env):
    """GUARDRAIL_PROMPT must contain 'Checkout' restriction text."""
    from agent.runner import GUARDRAIL_PROMPT

    assert "Checkout" in GUARDRAIL_PROMPT or "checkout" in GUARDRAIL_PROMPT.lower()


@pytest.mark.xfail(reason="Implemented in Task 2", strict=True)
def test_guardrail_prompt_blocks_payment_info(monkeypatch_env):
    """GUARDRAIL_PROMPT must reference credit card / payment info restriction."""
    from agent.runner import GUARDRAIL_PROMPT

    text = GUARDRAIL_PROMPT.lower()
    assert "credit card" in text or "payment" in text


@pytest.mark.xfail(reason="Implemented in Task 2", strict=True)
def test_guardrail_prompt_blocks_credentials(monkeypatch_env):
    """GUARDRAIL_PROMPT must reference credential submission restriction."""
    from agent.runner import GUARDRAIL_PROMPT

    text = GUARDRAIL_PROMPT.lower()
    assert "credential" in text or "password" in text or "username" in text


@pytest.mark.xfail(reason="Implemented in Task 2", strict=True)
def test_captcha_keywords_set_is_frozenset(monkeypatch_env):
    """CAPTCHA_KEYWORDS must be a frozenset for immutability."""
    from agent.runner import CAPTCHA_KEYWORDS

    assert isinstance(CAPTCHA_KEYWORDS, frozenset)


@pytest.mark.xfail(reason="Implemented in Task 2", strict=True)
def test_captcha_keywords_contains_core_terms(monkeypatch_env):
    """CAPTCHA_KEYWORDS must contain 'captcha', 'recaptcha', 'cloudflare'."""
    from agent.runner import CAPTCHA_KEYWORDS

    for term in ("captcha", "recaptcha", "cloudflare"):
        assert term in CAPTCHA_KEYWORDS, f"Expected {term!r} in CAPTCHA_KEYWORDS"


@pytest.mark.xfail(reason="Implemented in Task 2", strict=True)
def test_blocked_domains_contains_default_banks(monkeypatch_env):
    """SecurityWatchdog uses prohibited_domains; ensure core banking/payment domains are in the default set."""
    from agent.config import Settings

    cfg = Settings()
    assert "chase.com" in cfg.blocked_domains
    assert "paypal.com" in cfg.blocked_domains

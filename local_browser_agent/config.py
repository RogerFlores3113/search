"""Pydantic configuration models for the library."""
from __future__ import annotations

import os
from collections.abc import Mapping
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator

from local_browser_agent.safety import (
    DEFAULT_COMMERCE_PATTERNS,
    GUARDRAIL_PROMPT,
    SAFETY_DEFAULTS,
)


class ModelConfig(BaseModel):
    """Which LLM to use. ``extra`` is passed through to the provider constructor."""

    model_config = ConfigDict(extra="forbid")

    provider: str = "ollama"
    model: str | None = None
    api_key: SecretStr | None = None
    base_url: str | None = None
    temperature: float | None = None
    extra: dict[str, Any] = Field(default_factory=dict)


class BrowserConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    headless: bool = False
    channel: str | None = "chrome"
    executable_path: str | None = None
    cdp_url: str | None = None
    user_data_dir: str | None = None
    window_width: int = 1280
    window_height: int = 800
    llm_screenshot_width: int = 1024
    llm_screenshot_height: int = 640
    keep_alive: bool = False


class SafetyPolicy(BaseModel):
    """Enforcement layer. ``blocked_domains`` always contains ``SAFETY_DEFAULTS``."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    blocked_domains: frozenset[str] = SAFETY_DEFAULTS
    allowed_domains: list[str] | None = None
    guardrail_prompt: str = GUARDRAIL_PROMPT
    gate_commerce_clicks: bool = True
    commerce_patterns: list[str] = Field(default_factory=lambda: list(DEFAULT_COMMERCE_PATTERNS))

    @field_validator("blocked_domains", mode="before")
    @classmethod
    def _union_defaults(cls, v: Any) -> frozenset[str]:
        if v is None:
            v = ()
        if isinstance(v, str):
            v = [v]
        extra = {str(d).strip().lower() for d in v if str(d).strip()}
        return frozenset(SAFETY_DEFAULTS | extra)


class AgentConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model: ModelConfig = Field(default_factory=ModelConfig)
    browser: BrowserConfig = Field(default_factory=BrowserConfig)
    safety: SafetyPolicy = Field(default_factory=SafetyPolicy)
    max_steps: int = Field(default=25, ge=1)
    timeout_s: float = Field(default=600, gt=0)
    use_vision: bool = True
    system_prompt_extension: str | None = None
    use_judge: bool = False
    calculate_cost: bool = True
    on_captcha: Literal["fail", "pause"] = "fail"

    @classmethod
    def from_env(cls, prefix: str = "LBA_", env: Mapping[str, str] | None = None) -> AgentConfig:
        """Build a config from ``{prefix}*`` environment variables (convenience only).

        Recognised: PROVIDER, MODEL, API_KEY, BASE_URL, TEMPERATURE, HEADLESS, CHANNEL,
        EXECUTABLE_PATH, CDP_URL, USER_DATA_DIR, KEEP_ALIVE, MAX_STEPS, TIMEOUT_S,
        USE_VISION, USE_JUDGE, ALLOWED_DOMAINS and BLOCKED_DOMAINS (comma separated).
        ``ANTHROPIC_API_KEY`` / ``OPENAI_API_KEY`` are used when the provider matches
        and ``{prefix}API_KEY`` is unset.
        """
        e = os.environ if env is None else env

        def get(name: str) -> str | None:
            v = e.get(prefix + name)
            return v if v not in (None, "") else None

        def flag(name: str) -> bool | None:
            v = get(name)
            if v is None:
                return None
            return v.strip().lower() in ("1", "true", "yes", "on")

        def csv(name: str) -> list[str] | None:
            v = get(name)
            if v is None:
                return None
            return [x.strip() for x in v.split(",") if x.strip()]

        provider = (get("PROVIDER") or "ollama").lower()
        api_key = get("API_KEY")
        if api_key is None and provider in ("anthropic", "openai"):
            api_key = e.get(f"{provider.upper()}_API_KEY") or None

        model: dict[str, Any] = {"provider": provider}
        for key, name in (("model", "MODEL"), ("base_url", "BASE_URL")):
            if (v := get(name)) is not None:
                model[key] = v
        if api_key:
            model["api_key"] = SecretStr(api_key)
        if (v := get("TEMPERATURE")) is not None:
            model["temperature"] = float(v)

        browser: dict[str, Any] = {}
        for key, name in (("channel", "CHANNEL"), ("executable_path", "EXECUTABLE_PATH"),
                          ("cdp_url", "CDP_URL"), ("user_data_dir", "USER_DATA_DIR")):
            if (v := get(name)) is not None:
                browser[key] = v
        for key, name in (("headless", "HEADLESS"), ("keep_alive", "KEEP_ALIVE")):
            if (b := flag(name)) is not None:
                browser[key] = b

        safety: dict[str, Any] = {}
        if (v := csv("ALLOWED_DOMAINS")) is not None:
            safety["allowed_domains"] = v
        if (v := csv("BLOCKED_DOMAINS")) is not None:
            safety["blocked_domains"] = v

        top: dict[str, Any] = {}
        if (v := get("MAX_STEPS")) is not None:
            top["max_steps"] = int(v)
        if (v := get("TIMEOUT_S")) is not None:
            top["timeout_s"] = float(v)
        for key, name in (("use_vision", "USE_VISION"), ("use_judge", "USE_JUDGE")):
            if (b := flag(name)) is not None:
                top[key] = b

        return cls(
            model=ModelConfig(**model),
            browser=BrowserConfig(**browser),
            safety=SafetyPolicy(**safety),
            **top,
        )

"""Pydantic configuration models for the library."""
from __future__ import annotations

import os
from collections.abc import Mapping
from typing import Any, Literal

from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator, model_validator

from local_browser_agent.safety import (
    DEFAULT_COMMERCE_PATTERNS,
    GUARDRAIL_PROMPT,
    SAFETY_DEFAULTS,
    allowed_matches_blocked,
    normalize_allowed_domain,
)


class ModelConfig(BaseModel):
    """Which LLM to use.

    Args:
        provider: A registered provider name (``ollama``, ``anthropic``, ``openai``,
            ``openai_compatible``, ``litellm`` or one added with ``register_provider``).
            Normalised to lowercase.
        model: Model name; each built-in provider has a default except
            ``openai_compatible`` / ``litellm``.
        api_key: Optional here. Not read from the environment by the library
            (``AgentConfig.from_env`` does that); a missing key is reported by
            ``check_provider`` / ``build_llm``.
        base_url: Endpoint override. Must be an ``http(s)`` URL. Required for
            ``openai_compatible``.
        temperature: Sampling temperature, passed to the provider when set.
        extra: Passed through to the provider constructor.

    Raises:
        ValueError: (pydantic ``ValidationError``) for an unknown provider, a
            provider that needs ``base_url`` without one, or a malformed ``base_url``.
    """

    model_config = ConfigDict(extra="forbid")

    provider: str = "ollama"
    model: str | None = None
    api_key: SecretStr | None = None
    base_url: str | None = None
    temperature: float | None = None
    extra: dict[str, Any] = Field(default_factory=dict)

    @field_validator("provider")
    @classmethod
    def _known_provider(cls, v: str) -> str:
        from local_browser_agent.models import known_providers  # lazy: models imports config

        key = v.strip().lower()
        known = known_providers()
        if key not in known:
            raise ValueError(f"Unknown provider {v!r}. Known providers: {', '.join(known)}")
        return key

    @field_validator("base_url")
    @classmethod
    def _valid_base_url(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = v.strip()
        if not v:
            return None
        parsed = urlparse(v)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            raise ValueError(f"base_url must be an http(s) URL like 'http://localhost:11434', got {v!r}")
        return v

    @model_validator(mode="after")
    def _base_url_required(self) -> ModelConfig:
        if self.provider == "openai_compatible" and not self.base_url:
            raise ValueError("provider 'openai_compatible' requires base_url (e.g. 'https://host/v1')")
        return self


class BrowserConfig(BaseModel):
    """Browser launch/attach options.

    Args:
        headless: Run without a visible window.
        channel: Installed browser channel (``"chrome"``); ignored with ``executable_path`` or ``cdp_url``.
        executable_path: Path to a browser binary (takes precedence over ``channel``).
        cdp_url: Attach to a running browser (e.g. ``http://127.0.0.1:9222``) instead of launching one.
        user_data_dir: Reuse a Chrome profile directory (keeps logins).
        window_width, window_height: Browser window size in pixels.
        llm_screenshot_width, llm_screenshot_height: Size of screenshots sent to the model.
        keep_alive: Leave a launched browser open after the run.
    """

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


def _norm_domain(d: Any) -> str:
    return str(d).strip().lower().rstrip(".")


class SafetyPolicy(BaseModel):
    """Enforcement layer applied in the browser and tool layers (independent of the model).

    Args:
        blocked_domains: Extra domains to block. The effective set always contains
            ``SAFETY_DEFAULTS``, also after ``model_copy(update=...)`` or ``model_construct``.
            Entries are lowercased, stripped and lose a trailing dot.
        allowed_domains: If set, navigation is restricted to these domains. Entries are
            reduced to a plain hostname or ``*.hostname`` (scheme, port and path are stripped); bare
            ``*``, TLD-only wildcards like ``*.com`` and other globs raise ``ValueError``. Blocked domains win: an allowed domain equal to or
            under a blocked domain is dropped; if that leaves nothing, a ``ValueError`` is raised.
        guardrail_prompt: Text appended to the agent's system prompt.
        gate_commerce_clicks: Block clicks whose label matches ``commerce_patterns``
            unless an approval callback says yes.
        commerce_patterns: Labels treated as commerce actions.
        allow_evaluate: Let the agent run arbitrary page JavaScript without approval.
            Off by default: ``evaluate`` can submit forms, so it goes through the approval
            callback (and is denied when there is none).
    """

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    blocked_domains: frozenset[str] = SAFETY_DEFAULTS
    allowed_domains: list[str] | None = None
    guardrail_prompt: str = GUARDRAIL_PROMPT
    gate_commerce_clicks: bool = True
    commerce_patterns: list[str] = Field(default_factory=lambda: list(DEFAULT_COMMERCE_PATTERNS))
    allow_evaluate: bool = False

    @field_validator("blocked_domains", mode="before")
    @classmethod
    def _union_defaults(cls, v: Any) -> frozenset[str]:
        if v is None:
            v = ()
        if isinstance(v, str):
            v = [v]
        return frozenset(SAFETY_DEFAULTS | {_norm_domain(d) for d in v if _norm_domain(d)})

    @field_validator("allowed_domains", mode="before")
    @classmethod
    def _norm_allowed(cls, v: Any) -> Any:
        if v is None:
            return None
        if isinstance(v, str):
            v = [v]
        return [normalize_allowed_domain(d) for d in v if str(d).strip()]

    @model_validator(mode="after")
    def _blocked_wins(self) -> SafetyPolicy:
        self._normalize()
        return self

    def _normalize(self) -> None:
        """Re-establish invariants (idempotent); also run after model_copy/model_construct."""
        d = self.__dict__
        d["blocked_domains"] = frozenset(
            SAFETY_DEFAULTS | {_norm_domain(x) for x in d.get("blocked_domains") or () if _norm_domain(x)}
        )
        allowed = d.get("allowed_domains")
        if allowed is not None:
            blocked = d["blocked_domains"]
            kept = [
                n for x in allowed
                if not allowed_matches_blocked(n := normalize_allowed_domain(x), blocked)
            ]
            if allowed and not kept:
                raise ValueError("allowed_domains contains only blocked domains; blocked domains always win")
            d["allowed_domains"] = list(dict.fromkeys(kept))

    def model_post_init(self, __context: Any) -> None:
        self._normalize()

    def model_copy(self, *, update: Mapping[str, Any] | None = None, deep: bool = False) -> SafetyPolicy:
        new = super().model_copy(update=update, deep=deep)
        new._normalize()
        return new


class AgentConfig(BaseModel):
    """Everything a run needs.

    Args:
        model: :class:`ModelConfig`.
        browser: :class:`BrowserConfig`.
        safety: :class:`SafetyPolicy`.
        max_steps: Maximum agent steps, 1 to 500 (default 25).
        timeout_s: Wall-clock limit for the run in seconds, must be > 0 (default 600).
        use_vision: Send screenshots to the model.
        system_prompt_extension: Extra text appended to the system prompt.
        use_judge: Ask browser-use's judge to grade the result.
        calculate_cost: Track token cost when pricing is known.
        on_captcha: ``"fail"`` stops the run on a CAPTCHA; ``"pause"`` waits for ``resume()``.
    """

    model_config = ConfigDict(extra="forbid")

    model: ModelConfig = Field(default_factory=ModelConfig)
    browser: BrowserConfig = Field(default_factory=BrowserConfig)
    safety: SafetyPolicy = Field(default_factory=SafetyPolicy)
    max_steps: int = Field(default=25, ge=1, le=500)
    timeout_s: float = Field(default=600, gt=0)
    use_vision: bool = True
    system_prompt_extension: str | None = None
    use_judge: bool = False
    calculate_cost: bool = True
    on_captcha: Literal["fail", "pause"] = "fail"

    @classmethod
    def from_env(cls, prefix: str = "LBA_", env: Mapping[str, str] | None = None) -> AgentConfig:
        """Build a config from ``{prefix}*`` environment variables (convenience only).

        Variables (names shown with the default ``LBA_`` prefix; empty values count as unset):

        - ``LBA_PROVIDER`` (str, default ``ollama``), ``LBA_MODEL`` (str), ``LBA_API_KEY`` (str),
          ``LBA_BASE_URL`` (http(s) URL), ``LBA_TEMPERATURE`` (float)
        - ``LBA_HEADLESS`` (bool), ``LBA_KEEP_ALIVE`` (bool), ``LBA_CHANNEL`` (str),
          ``LBA_EXECUTABLE_PATH`` (str), ``LBA_CDP_URL`` (str), ``LBA_USER_DATA_DIR`` (str)
        - ``LBA_MAX_STEPS`` (int, 1-500), ``LBA_TIMEOUT_S`` (float, > 0)
        - ``LBA_USE_VISION`` (bool), ``LBA_USE_JUDGE`` (bool)
        - ``LBA_ALLOWED_DOMAINS`` / ``LBA_BLOCKED_DOMAINS`` (comma separated)
        - ``LBA_ALLOW_EVALUATE`` (bool): run page JavaScript without approval

        Booleans accept 1/0, true/false, yes/no, on/off (any case). ``ANTHROPIC_API_KEY`` /
        ``OPENAI_API_KEY`` are used when the provider matches and ``LBA_API_KEY`` is unset.
        ``LBA_ALLOW_TELEMETRY=1`` (read at import time, not here) re-enables browser-use telemetry.

        Raises:
            ValueError: naming the variable and the expected type, e.g.
                ``LBA_MAX_STEPS must be an integer, got 'abc'``; or a validation error
                for out-of-range / invalid values.
        """
        e = os.environ if env is None else env

        def get(name: str) -> str | None:
            v = e.get(prefix + name)
            return v if v not in (None, "") else None

        def flag(name: str) -> bool | None:
            v = get(name)
            if v is None:
                return None
            low = v.strip().lower()
            if low in ("1", "true", "yes", "on"):
                return True
            if low in ("0", "false", "no", "off"):
                return False
            raise ValueError(f"{prefix}{name} must be a boolean (1/0, true/false, yes/no, on/off), got {v!r}")

        def num(name: str, kind: type, label: str) -> Any:
            v = get(name)
            if v is None:
                return None
            try:
                return kind(v.strip())
            except ValueError:
                raise ValueError(f"{prefix}{name} must be {label}, got {v!r}") from None

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
        if (t := num("TEMPERATURE", float, "a number")) is not None:
            model["temperature"] = t

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
        if (b := flag("ALLOW_EVALUATE")) is not None:
            safety["allow_evaluate"] = b

        top: dict[str, Any] = {}
        if (i := num("MAX_STEPS", int, "an integer")) is not None:
            top["max_steps"] = i
        if (t := num("TIMEOUT_S", float, "a number")) is not None:
            top["timeout_s"] = t
        for key, name in (("use_vision", "USE_VISION"), ("use_judge", "USE_JUDGE")):
            if (b := flag(name)) is not None:
                top[key] = b

        return cls(
            model=ModelConfig(**model),
            browser=BrowserConfig(**browser),
            safety=SafetyPolicy(**safety),
            **top,
        )

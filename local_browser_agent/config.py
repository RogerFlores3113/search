"""Pydantic configuration models for the library."""
from __future__ import annotations

import logging
import os
from collections.abc import Iterable, Mapping
from typing import Any, Literal

from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator, model_validator

from local_browser_agent.redact import redact_url
from local_browser_agent.safety import (
    DEFAULT_COMMERCE_PATTERNS,
    GUARDRAIL_PROMPT,
    SAFETY_DEFAULTS,
    allowed_matches_blocked,
    normalize_allowed_domain,
    normalize_blocked_domain,
)

logger = logging.getLogger("local_browser_agent")


_MASK = "***"


def _safe_url(v: Any) -> Any:
    """Redact userinfo, query and fragment of a URL-ish value (for repr / errors / safe_dump)."""
    return redact_url(v) if isinstance(v, str) and v else v


#: Environment variable names (without the prefix) read by ``AgentConfig.from_env``, keyed by the
#: pydantic field path they feed. Used to name the variable in validation errors.
_ENV_FIELD_VARS: dict[str, str] = {
    "model.provider": "PROVIDER", "model.model": "MODEL", "model.api_key": "API_KEY",
    "model.base_url": "BASE_URL", "model.temperature": "TEMPERATURE",
    "browser.channel": "CHANNEL", "browser.executable_path": "EXECUTABLE_PATH", "browser.cdp_url": "CDP_URL",
    "browser.user_data_dir": "USER_DATA_DIR", "browser.headless": "HEADLESS", "browser.keep_alive": "KEEP_ALIVE",
    "safety.allowed_domains": "ALLOWED_DOMAINS", "safety.blocked_domains": "BLOCKED_DOMAINS",
    "safety.allow_evaluate": "ALLOW_EVALUATE", "safety.allow_local_network": "ALLOW_LOCAL_NETWORK",
    "safety.approval_timeout_s": "APPROVAL_TIMEOUT_S",
    "max_steps": "MAX_STEPS", "timeout_s": "TIMEOUT_S", "use_vision": "USE_VISION", "use_judge": "USE_JUDGE",
}

#: ``LBA_*`` names used elsewhere in the repo (not read by ``from_env``); they never warn as unknown.
_INTERNAL_ENV_NAMES = frozenset({"DATA_DIR", "ALLOW_TELEMETRY", "MCP_STRICT"})


def unknown_env_warnings(prefix: str = "LBA_", env: Mapping[str, str] | None = None) -> list[str]:
    """One message per ``{prefix}*`` variable that nothing reads, with a did-you-mean suggestion.

    Warnings only: a typo like ``LBA_TIMEOUT`` (for ``LBA_TIMEOUT_S``) is otherwise silently ignored.
    """
    import difflib

    e = os.environ if env is None else env
    known = sorted(set(_ENV_FIELD_VARS.values()) | _INTERNAL_ENV_NAMES)
    out: list[str] = []
    for name in sorted(e):
        if not name.startswith(prefix):
            continue
        bare = name[len(prefix):]
        if bare in known:
            continue
        near = difflib.get_close_matches(bare, known, n=1, cutoff=0.6)
        if not near:
            near = [k for k in known if k.startswith(bare) or bare.startswith(k)][:1]
        hint = f"; did you mean {prefix}{near[0]}?" if near else ""
        out.append(f"warning: unknown environment variable {name} is ignored{hint}")
    return out


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

    Secrets: ``repr()``, ``str()`` and validation errors redact ``base_url`` userinfo /
    query and mask ``extra`` values. ``model_dump()`` / ``model_dump_json()`` return the
    real values (they are for persistence); use :meth:`safe_dump` for logging or display.
    Assignment is validated (``cfg.base_url = "ftp://x"`` raises).
    """

    model_config = ConfigDict(extra="forbid", validate_assignment=True, hide_input_in_errors=True)

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
            raise ValueError(
                f"base_url must be an http(s) URL like 'http://localhost:11434', got {_safe_url(v)!r}")
        return v

    @model_validator(mode="after")
    def _base_url_required(self) -> ModelConfig:
        if self.provider == "openai_compatible" and not self.base_url:
            raise ValueError("provider 'openai_compatible' requires base_url (e.g. 'https://host/v1')")
        return self

    def __repr_args__(self):
        for name, value in super().__repr_args__():
            if name == "base_url":
                value = _safe_url(value)
            elif name == "extra" and isinstance(value, dict):
                value = {k: _MASK for k in value}
            yield name, value

    def safe_dump(self) -> dict[str, Any]:
        """JSON-safe dict with secrets masked: api_key, ``base_url`` userinfo/query, ``extra`` values."""
        d = self.model_dump(mode="json")
        d["base_url"] = _safe_url(d.get("base_url"))
        d["extra"] = {k: _MASK for k in d.get("extra") or {}}
        return d


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
        allow_downloads: Let the page save downloads (and auto-download PDFs). Off by default.

    ``cdp_url`` must be an ``http(s)`` / ``ws(s)`` URL with a host. ``repr()`` and
    validation errors redact its userinfo and query; ``model_dump()`` keeps the real value
    (use :meth:`safe_dump` for logs). Assignment is validated.
    """

    model_config = ConfigDict(extra="forbid", validate_assignment=True, hide_input_in_errors=True)

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
    allow_downloads: bool = False

    @field_validator("cdp_url")
    @classmethod
    def _valid_cdp_url(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = v.strip()
        if not v:
            return None
        try:
            parsed = urlparse(v)
            host = parsed.hostname
        except ValueError:
            parsed, host = None, None
        if parsed is None or parsed.scheme not in ("http", "https", "ws", "wss") or not host:
            raise ValueError(
                "cdp_url must be an http(s) or ws(s) URL with a host, like 'http://127.0.0.1:9222', "
                f"got {_safe_url(v)!r}")
        return v

    def __repr_args__(self):
        for name, value in super().__repr_args__():
            yield name, (_safe_url(value) if name == "cdp_url" else value)

    def safe_dump(self) -> dict[str, Any]:
        """``model_dump`` with ``cdp_url`` userinfo and query removed."""
        d = self.model_dump(mode="json")
        d["cdp_url"] = _safe_url(d.get("cdp_url"))
        return d


def _norm_domain(d: Any) -> str:
    """Normalised blocked domain; "" for a blank entry, ValueError for one with no valid host."""
    return normalize_blocked_domain(d) if str(d).strip() else ""


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
        allow_local_network: Let the agent's browser reach ``localhost``, loopback, private
            and link-local addresses (the local web app, router admin pages, cloud metadata
            at 169.254.169.254). Off by default. While off, the browser blocks ``localhost``,
            ``*.localhost`` / ``*.local`` / ``*.internal`` / ``*.lan`` / ``*.home.arpa`` /
            ``*.localdomain`` / ``*.intranet``, single-label hostnames and every IP-address URL
            (``http://8.8.8.8/`` is blocked too; use a hostname). DNS names that resolve to
            private addresses are NOT caught (no DNS lookups); use ``allowed_domains`` for
            strict isolation. Also ``start_url`` / ``allowed_domains`` entries that are local are
            rejected. Set it only for local test fixtures or dev servers.
        approval_timeout_s: Seconds to wait for the approval callback before the gated action is
            denied. ``None`` or ``0`` waits forever; must be ``>= 0``. Default 120.
    """

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    blocked_domains: frozenset[str] = SAFETY_DEFAULTS
    allowed_domains: list[str] | None = None
    guardrail_prompt: str = GUARDRAIL_PROMPT
    gate_commerce_clicks: bool = True
    commerce_patterns: list[str] = Field(default_factory=lambda: list(DEFAULT_COMMERCE_PATTERNS))
    allow_evaluate: bool = False
    allow_local_network: bool = False
    approval_timeout_s: float | None = 120.0

    @classmethod
    def strict(cls, allowed_domains: Iterable[str] | str, **kw: Any) -> SafetyPolicy:
        """Preset for profiles that are logged in to real accounts.

        Requires a non-empty ``allowed_domains`` allow-list (navigation is restricted to it; blocked
        domains still win) and forces ``gate_commerce_clicks=True`` so purchases and irreversible
        actions (account deletion, subscription cancellation, money transfers; these are gated
        whenever ``gate_commerce_clicks`` is on, as ``ActionRequest(kind="irreversible")``) need
        approval. Other fields (``allow_evaluate``, ``allow_local_network``, ...) keep their safe
        defaults unless passed via ``**kw``; ``gate_commerce_clicks`` cannot be switched off here.
        Without an approval callback every gated action is denied.
        """
        if isinstance(allowed_domains, str):
            allowed_domains = [allowed_domains]
        domains = [d for d in (allowed_domains or []) if str(d).strip()]
        if not domains:
            raise ValueError("SafetyPolicy.strict requires a non-empty allowed_domains list")
        kw.pop("gate_commerce_clicks", None)
        return cls(allowed_domains=domains, gate_commerce_clicks=True, **kw)

    @field_validator("approval_timeout_s")
    @classmethod
    def _check_approval_timeout(cls, v: float | None) -> float | None:
        if v is not None and v < 0:
            raise ValueError("approval_timeout_s must be >= 0 (0 or None waits forever)")
        return v

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
            kept: list[str] = []
            dropped: list[str] = []
            for x in allowed:
                n = normalize_allowed_domain(x)
                (dropped if allowed_matches_blocked(n, blocked) else kept).append(n)
            if dropped:
                logger.warning(
                    "allowed_domains entries %s were dropped because they cover or sit under a blocked domain "
                    "(blocked domains always win)", sorted(set(dropped)))
            if allowed and not kept:
                raise ValueError(
                    "allowed_domains contains only blocked domains; blocked domains always win "
                    f"(dropped: {sorted(set(dropped))})")
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

    Assignment is validated (``cfg.max_steps = -5`` raises ``ValidationError``). ``repr()``
    redacts credentials; ``model_dump()`` / ``model_dump_json()`` return real secret values
    (``base_url`` / ``cdp_url`` userinfo and query, ``ModelConfig.extra``), so use
    :meth:`safe_dump` for logging or display.
    """

    model_config = ConfigDict(extra="forbid", validate_assignment=True, hide_input_in_errors=True)

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

    def safe_dump(self) -> dict[str, Any]:
        """JSON-safe dict with credentials masked (see :meth:`ModelConfig.safe_dump`)."""
        d = self.model_dump(mode="json")
        d["model"] = self.model.safe_dump()
        d["browser"] = self.browser.safe_dump()
        return d

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
        - ``LBA_ALLOW_LOCAL_NETWORK`` (bool): let the browser reach localhost / private addresses
        - ``LBA_APPROVAL_TIMEOUT_S`` (float, >= 0): seconds to wait for an approval; 0 waits forever

        Booleans accept 1/0, true/false, yes/no, on/off (any case). ``ANTHROPIC_API_KEY`` /
        ``OPENAI_API_KEY`` are used when the provider matches and ``LBA_API_KEY`` is unset.
        ``LBA_ALLOW_TELEMETRY=1`` (read at import time, not here) re-enables browser-use telemetry.

        Raises:
            ValueError: naming the variable and the expected type, e.g.
                ``LBA_MAX_STEPS must be an integer, got 'abc'``, or a validation message
                for out-of-range / invalid values. Every problem is collected: the message
                has one line per problem.
        """
        e = os.environ if env is None else env
        problems: list[str] = []  # every bad variable is reported together, not just the first

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
            problems.append(f"{prefix}{name} must be a boolean (1/0, true/false, yes/no, on/off), got {v!r}")
            return None

        def num(name: str, kind: type, label: str) -> Any:
            v = get(name)
            if v is None:
                return None
            try:
                return kind(v.strip())
            except ValueError:
                problems.append(f"{prefix}{name} must be {label}, got {v!r}")
                return None

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
        if (b := flag("ALLOW_LOCAL_NETWORK")) is not None:
            safety["allow_local_network"] = b
        if (t := num("APPROVAL_TIMEOUT_S", float, "a number")) is not None:
            safety["approval_timeout_s"] = t

        top: dict[str, Any] = {}
        if (i := num("MAX_STEPS", int, "an integer")) is not None:
            top["max_steps"] = i
        if (t := num("TIMEOUT_S", float, "a number")) is not None:
            top["timeout_s"] = t
        for key, name in (("use_vision", "USE_VISION"), ("use_judge", "USE_JUDGE")):
            if (b := flag(name)) is not None:
                top[key] = b

        from local_browser_agent.log import format_validation_error

        def build(factory: Any, kwargs: dict[str, Any], label: str | None = None) -> Any:
            try:
                return factory(**kwargs)
            except ValueError as exc:  # a pydantic ValidationError is a ValueError
                for ln in format_validation_error(exc).splitlines():
                    field, sep, msg = ln.partition(": ")
                    path = f"{label}.{field}" if label and sep else field
                    var = _ENV_FIELD_VARS.get(path) if sep else None
                    if var is None:
                        problems.append(f"{label}.{ln}" if label and sep else ln)
                        continue
                    # Name the variable the user set, not the pydantic field ("LBA_MAX_STEPS (max_steps): ...").
                    got = ""
                    if field in kwargs and var != "API_KEY":
                        shown = _safe_url(kwargs[field]) if var == "BASE_URL" else kwargs[field]
                        got = f" (got {shown!r})"
                    problems.append(f"{prefix}{var} ({field}): {msg}{got}")
                return None

        model_cfg = build(ModelConfig, model, "model")
        browser_cfg = build(BrowserConfig, browser, "browser")
        safety_cfg = build(SafetyPolicy, safety, "safety")
        # Top-level fields are validated even when a section failed (defaults stand in for it).
        cfg = build(cls, {"model": model_cfg or ModelConfig(), "browser": browser_cfg or BrowserConfig(),
                          "safety": safety_cfg or SafetyPolicy(), **top})
        if problems:
            raise ValueError("\n".join(dict.fromkeys(problems)))
        return cfg

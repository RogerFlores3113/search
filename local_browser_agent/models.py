"""LLM provider registry."""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from local_browser_agent.config import ModelConfig

ProviderFactory = Callable[[ModelConfig], Any]

DEFAULT_MODELS: dict[str, str] = {
    "ollama": "qwen2.5vl:7b",
    "anthropic": "claude-sonnet-4-5",
    "openai": "gpt-4o",
}
OLLAMA_DEFAULT_HOST = "http://localhost:11434"
OLLAMA_NUM_CTX = 32000

_REGISTRY: dict[str, ProviderFactory] = {}
_CUSTOM_DEFAULTS: dict[str, str] = {}


class PreFlightError(RuntimeError):
    """Raised by :func:`check_provider` when the provider is unusable."""


def register_provider(name: str, factory: ProviderFactory, *, default_model: str | None = None) -> None:
    """Register (or replace) a provider. ``factory(ModelConfig) -> BaseChatModel``."""
    key = name.strip().lower()
    if not key:
        raise ValueError("provider name must be non-empty")
    _REGISTRY[key] = factory
    if default_model:
        _CUSTOM_DEFAULTS[key] = default_model
    else:
        _CUSTOM_DEFAULTS.pop(key, None)


def known_providers() -> list[str]:
    return sorted(_REGISTRY)


def default_model(provider: str) -> str | None:
    key = provider.lower()
    return _CUSTOM_DEFAULTS.get(key) or DEFAULT_MODELS.get(key)


def resolve_model_name(cfg: ModelConfig) -> str:
    """Model name to use: the configured one, the provider default, else the provider name.

    Built-in providers without a default (``openai_compatible``, ``litellm``) raise
    ``ValueError``; a custom registered provider falls back to its own name so
    events and traces never carry an empty model name.
    """
    name = cfg.model or default_model(cfg.provider)
    if name:
        return name
    if cfg.provider.lower() in _BUILTIN_PROVIDERS:
        raise ValueError(f"Provider {cfg.provider!r} has no default model; set ModelConfig.model")
    return cfg.provider


_BUILTIN_PROVIDERS = frozenset({"ollama", "anthropic", "openai", "openai_compatible", "litellm"})
_KEY_HINTS = {
    "anthropic": ("Anthropic", "ANTHROPIC_API_KEY"),
    "openai": ("OpenAI", "OPENAI_API_KEY"),
}


def _missing_key_message(provider: str) -> str:
    label, env = _KEY_HINTS[provider]
    return f"{label} API key is not set. Set {env} or LBA_API_KEY."


def _key(cfg: ModelConfig, env_hint: str = "") -> str:
    if cfg.api_key is None or not cfg.api_key.get_secret_value():
        provider = cfg.provider.lower()
        if provider in _KEY_HINTS:
            raise ValueError(_missing_key_message(provider))
        raise ValueError(f"{cfg.provider}: api_key is required ({env_hint or 'set LBA_API_KEY'})")
    return cfg.api_key.get_secret_value()


def _ollama(cfg: ModelConfig) -> Any:
    from browser_use import ChatOllama

    options: dict[str, Any] = {"num_ctx": OLLAMA_NUM_CTX}
    if cfg.temperature is not None:
        options["temperature"] = cfg.temperature
    options.update(cfg.extra)
    return ChatOllama(
        model=resolve_model_name(cfg),
        host=cfg.base_url or OLLAMA_DEFAULT_HOST,
        ollama_options=options,
    )


def _anthropic(cfg: ModelConfig) -> Any:
    from browser_use import ChatAnthropic

    kwargs: dict[str, Any] = dict(cfg.extra)
    if cfg.base_url:
        kwargs["base_url"] = cfg.base_url
    if cfg.temperature is not None:
        kwargs["temperature"] = cfg.temperature
    return ChatAnthropic(model=resolve_model_name(cfg), api_key=_key(cfg), **kwargs)


def _openai(cfg: ModelConfig) -> Any:
    from browser_use import ChatOpenAI

    kwargs: dict[str, Any] = dict(cfg.extra)
    if cfg.base_url:
        kwargs["base_url"] = cfg.base_url
    if cfg.temperature is not None:
        kwargs["temperature"] = cfg.temperature
    return ChatOpenAI(model=resolve_model_name(cfg), api_key=_key(cfg), **kwargs)


def _openai_compatible(cfg: ModelConfig) -> Any:
    from browser_use import ChatOpenAI

    if not cfg.base_url:
        raise ValueError("openai_compatible requires base_url")
    kwargs: dict[str, Any] = dict(cfg.extra)
    if cfg.temperature is not None:
        kwargs["temperature"] = cfg.temperature
    key = cfg.api_key.get_secret_value() if cfg.api_key else "not-needed"
    return ChatOpenAI(model=resolve_model_name(cfg), api_key=key, base_url=cfg.base_url, **kwargs)


def _litellm(cfg: ModelConfig) -> Any:
    from browser_use import ChatLiteLLM

    kwargs: dict[str, Any] = dict(cfg.extra)
    if cfg.base_url:
        kwargs["api_base"] = cfg.base_url
    if cfg.temperature is not None:
        kwargs["temperature"] = cfg.temperature
    if cfg.api_key:
        kwargs["api_key"] = cfg.api_key.get_secret_value()
    return ChatLiteLLM(model=resolve_model_name(cfg), **kwargs)


for _name, _factory in (
    ("ollama", _ollama),
    ("anthropic", _anthropic),
    ("openai", _openai),
    ("openai_compatible", _openai_compatible),
    ("litellm", _litellm),
):
    register_provider(_name, _factory)


def build_llm(cfg: ModelConfig) -> Any:
    """Construct the chat model for ``cfg``. Never reads environment variables."""
    key = cfg.provider.strip().lower()
    factory = _REGISTRY.get(key)
    if factory is None:
        raise ValueError(f"Unknown provider {cfg.provider!r}. Known providers: {', '.join(known_providers())}")
    return factory(cfg)


async def check_provider(cfg: ModelConfig) -> None:
    """Optional pre-flight check. Raises :class:`PreFlightError`; never prints.

    Network use: ``ollama`` lists local models (``/api/tags``); ``anthropic`` and ``openai``
    make a small live API call (list models) to validate the key; other providers are not checked.
    """
    import httpx

    provider = cfg.provider.lower()
    if provider == "ollama":
        host = (cfg.base_url or OLLAMA_DEFAULT_HOST).rstrip("/")
        model = resolve_model_name(cfg)
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(f"{host}/api/tags")
                resp.raise_for_status()
                models = [m["name"] for m in resp.json().get("models", [])]
        except httpx.HTTPError as e:
            raise PreFlightError(
                f"Ollama is not running or unreachable at {host}. Start it with `ollama serve`, "
                f"then `ollama pull {model}`."
            ) from e
        if model.split(":")[0] not in [m.split(":")[0] for m in models]:
            raise PreFlightError(f"Ollama model {model!r} is not pulled. Run `ollama pull {model}`.")
    elif provider == "anthropic":
        key = cfg.api_key.get_secret_value() if cfg.api_key else None
        if not key:
            raise PreFlightError(_missing_key_message("anthropic"))
        try:
            import anthropic

            await anthropic.AsyncAnthropic(api_key=key).models.list()
        except anthropic.AuthenticationError as e:
            raise PreFlightError("Anthropic API key is invalid") from e
        except Exception as e:
            raise PreFlightError(f"Cannot reach Anthropic API: {e}") from e
    elif provider == "openai":
        key = cfg.api_key.get_secret_value() if cfg.api_key else None
        if not key:
            raise PreFlightError(_missing_key_message("openai"))
        base = (cfg.base_url or "https://api.openai.com/v1").rstrip("/")
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(f"{base}/models", headers={"Authorization": f"Bearer {key}"})
            if resp.status_code == 401:
                raise PreFlightError("OpenAI API key is invalid")
            resp.raise_for_status()
        except PreFlightError:
            raise
        except Exception as e:
            raise PreFlightError(f"Cannot reach OpenAI API: {e}") from e
    # other providers: nothing to check

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import SecretStr
from pydantic_settings import (
    BaseSettings,
    JsonConfigSettingsSource,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
)

SAFETY_DEFAULTS: frozenset[str] = frozenset({
    # Banking
    "chase.com", "wellsfargo.com", "bankofamerica.com", "citi.com", "usbank.com",
    # Payment
    "paypal.com", "venmo.com", "stripe.com", "square.com", "braintree.com",
    # Government
    "irs.gov", "ssa.gov", "healthcare.gov", "va.gov", "dhs.gov",
    "state.gov", "fbi.gov", "whitehouse.gov",
    # Medical
    "labcorp.com", "questdiagnostics.com", "epic.com", "mychart.com",
    # Credential / Identity
    "lastpass.com", "1password.com", "bitwarden.com", "dashlane.com",
    "nordpass.com", "okta.com", "auth0.com",
})


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="",
        env_file=".env",
        extra="ignore",
    )

    provider: str = "ollama"
    ollama_host: str = "http://localhost:11434"
    ollama_model: str = "qwen3-vl:8b"
    max_steps: int = 25
    session_timeout: int = 600  # seconds

    # Browser window size — kept sub-fullscreen so the window is moveable
    browser_width: int = 1280
    browser_height: int = 800

    # Screenshot size sent to the LLM — smaller = fewer tokens = faster loops
    llm_screenshot_width: int = 1024
    llm_screenshot_height: int = 640

    # Anthropic provider
    anthropic_api_key: SecretStr | None = None
    anthropic_model: str = "claude-sonnet-4-5"

    # OpenAI provider
    openai_api_key: SecretStr | None = None
    openai_model: str = "gpt-4o"

    # User-added blocked domains (loaded from settings.json via JsonConfigSettingsSource)
    user_domains: list[str] = []

    @property
    def blocked_domains(self) -> set[str]:
        """Two-tier merge: safety defaults (code) + user-added domains (settings.json).

        SAFETY_DEFAULTS is always included regardless of user_domains — the user
        cannot shrink the enforcement layer (T-11-06 mitigation).
        """
        return SAFETY_DEFAULTS | set(self.user_domains)

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        # Lazy import to avoid circular imports at module load time.
        from agent.paths import get_settings_path

        json_source = JsonConfigSettingsSource(settings_cls, json_file=get_settings_path())
        # Precedence: init > settings.json > env > .env > file secrets
        return init_settings, json_source, env_settings, dotenv_settings, file_secret_settings


config = Settings()

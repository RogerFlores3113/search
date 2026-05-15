from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


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

    # Guardrails — hardcoded default; not a .env field in Phase 2
    # (pydantic-settings set[str] coercion from env var is unverified — see RESEARCH.md A3)
    blocked_domains: set[str] = {
        "chase.com", "wellsfargo.com", "bankofamerica.com",
        "citi.com", "usbank.com", "paypal.com", "venmo.com",
        "stripe.com", "square.com", "braintree.com",
    }


config = Settings()

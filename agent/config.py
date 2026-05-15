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


config = Settings()

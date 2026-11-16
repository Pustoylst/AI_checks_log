"""Application configuration loaded from environment variables."""

from functools import lru_cache
from urllib.parse import urlparse

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Local inference settings and optional GitHub integration."""

    ollama_base_url: str = "http://127.0.0.1:11434"
    ollama_model: str = "qwen3:8b"
    ollama_timeout_seconds: float = Field(default=180, gt=0)
    ollama_num_ctx: int = Field(default=8192, ge=1024)
    github_token: SecretStr | None = None
    github_repository: str | None = None
    github_api_url: str = "https://api.github.com"
    github_default_branch: str = "main"
    ci_poll_interval_seconds: int = 60
    ci_state_dir: str = "../agent-ci-runtime"

    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore", case_sensitive=False,
    )

    @field_validator("ollama_base_url")
    @classmethod
    def local_ollama_only(cls, value: str) -> str:
        """Prevent accidental forwarding of logs to a remote inference endpoint."""
        parsed = urlparse(value)
        if (parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
                or parsed.username or parsed.password or parsed.query or parsed.fragment
                or parsed.path not in {"", "/"}):
            raise ValueError("OLLAMA_BASE_URL должен указывать на локальный HTTP-сервер Ollama")
        return value.rstrip("/")


@lru_cache
def get_settings() -> Settings:
    """Return cached application settings."""
    return Settings()

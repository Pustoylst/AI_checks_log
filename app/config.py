"""Application configuration loaded from environment variables."""

from functools import lru_cache

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings for the log analysis application."""

    gigachat_credentials: SecretStr | None = None
    gigachat_scope: str = "GIGACHAT_API_PERS"
    gigachat_model: str = "GigaChat-2-Max"
    gigachat_fallback_model: str = "GigaChat-2"
    gigachat_verify_ssl_certs: bool = False
    github_token: SecretStr | None = None
    github_repository: str | None = None
    github_api_url: str = "https://api.github.com"
    github_default_branch: str = "main"
    ci_poll_interval_seconds: int = 60

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    @property
    def has_gigachat_credentials(self) -> bool:
        """Return whether a non-empty GigaChat credential value is configured."""

        return bool(self.gigachat_credentials and self.gigachat_credentials.get_secret_value().strip())


@lru_cache
def get_settings() -> Settings:
    """Return cached application settings."""

    return Settings()

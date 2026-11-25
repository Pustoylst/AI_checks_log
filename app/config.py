"""Application configuration loaded from environment variables."""

from functools import lru_cache
from pathlib import Path
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
    log_share_path: str = r"\\192.168.240.2\Logs"
    log_share_max_files: int = Field(default=200, ge=1, le=1000)
    log_share_scan_limit: int = Field(default=5000, ge=1, le=100000)
    log_preprocess_budget_chars: int = Field(default=14000, ge=4000, le=60000)
    log_preprocess_max_bytes: int = Field(default=512 * 1024 * 1024, ge=1024 * 1024)
    log_overview_budget_chars: int = Field(default=16000, ge=4000, le=60000)
    log_overview_max_files: int = Field(default=1000, ge=1, le=5000)
    log_overview_max_bytes: int = Field(default=3 * 1024 * 1024 * 1024, ge=1024 * 1024)
    directum_docs_path: Path = Path(__file__).resolve().parents[2] / "rx262"
    rag_vector_enabled: bool = True
    rag_embedding_model: str = "bge-m3:latest"
    rag_embedding_batch_size: int = Field(default=16, ge=1, le=128)
    rag_vector_min_similarity: float = Field(default=0.45, ge=0, le=1)

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

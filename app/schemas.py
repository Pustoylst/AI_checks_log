"""Pydantic models for incoming log data."""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


class LogPayload(BaseModel):
    """Accept a non-empty JSON object while keeping arbitrary log fields."""

    model_config = ConfigDict(extra="allow")

    timestamp: str | None = None
    level: str | None = None
    message: str | None = None
    trace_id: str | None = None
    repo_paths: list[str] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def require_non_empty_object(cls, value: Any) -> Any:
        if not isinstance(value, dict) or not value:
            raise ValueError("Лог должен быть непустым JSON-объектом")
        return value


class AnalyzeResponse(BaseModel):
    """Successful analysis response."""

    result: str
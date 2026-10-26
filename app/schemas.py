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


class FixProposal(BaseModel):
    """A precise, reviewable replacement proposed by the agent."""

    path: str
    explanation: str
    old_text: str
    new_text: str


class ApplyFixRequest(FixProposal):
    """A fix proposal plus explicit user consent."""

    approved: bool = False


class ApplyFixResponse(BaseModel):
    """Result of applying an approved fix."""

    path: str
    backup_path: str
    message: str


class PullRequestRequest(BaseModel):
    """Approved proposal metadata used to create an agent Pull Request."""

    approved: bool = False
    path: str
    explanation: str
    old_text: str
    new_text: str
    base_branch: str = "main"
    title: str = "fix: apply agent proposal"
    run_id: int | None = None
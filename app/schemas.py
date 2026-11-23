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


class ShareLogFile(BaseModel):
    """One log file discovered in the configured network share."""

    name: str
    path: str
    size: int
    modified: str | None = None


class ShareLogsResponse(BaseModel):
    """Bounded listing of the network log share."""

    root: str
    count: int
    files: list[ShareLogFile]


class ShareLogAnalyzeResponse(AnalyzeResponse):
    """Analysis result for a log read directly from the network share."""

    source: str
    preprocessed: bool = False
    stats: dict[str, Any] | None = None


class ShareLogPreprocessResponse(BaseModel):
    """Compact report produced from a large log without calling the model."""

    source: str
    report: str
    stats: dict[str, Any]


class ShareOverviewResponse(BaseModel):
    """Aggregated report for many logs without calling the model."""

    root: str
    report: str
    stats: dict[str, Any]


class ShareOverviewAnalyzeRequest(BaseModel):
    """A previously built overview that should be analysed by the model."""

    report: str = Field(min_length=1, max_length=60000)
    stats: dict[str, Any] | None = None
    question: str | None = Field(default=None, max_length=2000)


class FixProposal(BaseModel):
    """A precise, reviewable replacement proposed by the agent."""

    path: str
    explanation: str
    old_text: str
    new_text: str
    analysis: str | None = None
    run_id: int | None = None
    description: str | None = None


class ApplyFixRequest(FixProposal):
    """A fix proposal plus explicit user consent."""

    approved: bool = False


class ApplyFixResponse(BaseModel):
    """Result of applying an approved fix."""

    path: str
    message: str


class PullRequestRequest(BaseModel):
    """Approved proposal metadata used to create an agent Pull Request."""

    approved: bool = False
    path: str
    explanation: str
    old_text: str
    new_text: str
    analysis: str | None = None
    description: str | None = None
    base_branch: str = "main"
    title: str = "fix: apply agent proposal"
    run_id: int | None = None
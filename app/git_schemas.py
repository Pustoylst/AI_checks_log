"""API schemas for repository and CI operations."""

from pydantic import BaseModel, Field


class GitActionRequest(BaseModel):
    approved: bool = False
    message: str = ""
    paths: list[str] = Field(default_factory=list)


class MergeRequest(BaseModel):
    approved: bool = False
    source_branch: str
    target_branch: str

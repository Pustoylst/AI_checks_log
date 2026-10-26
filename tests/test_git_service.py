import subprocess
from pathlib import Path

import pytest

from app.git_service import commit_and_push, merge_branch, repository_status


def init_repo(path: Path) -> None:
    subprocess.run(["git", "init", "-b", "main"], cwd=path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=path, check=True)


def test_repository_status_reads_local_git(tmp_path: Path) -> None:
    init_repo(tmp_path)
    (tmp_path / "README.md").write_text("test\n", encoding="utf-8")

    status = repository_status(tmp_path)

    assert status["branch"] == "main"
    assert "README.md" in status["changes"][0]


def test_commit_requires_approval(tmp_path: Path) -> None:
    init_repo(tmp_path)

    with pytest.raises(PermissionError):
        commit_and_push(tmp_path, ["README.md"], "test commit", False)


def test_merge_requires_approval(tmp_path: Path) -> None:
    init_repo(tmp_path)

    with pytest.raises(PermissionError):
        merge_branch(tmp_path, "feature", "main", False)
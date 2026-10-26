import subprocess
from pathlib import Path

import pytest

from app.git_service import repository_status


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


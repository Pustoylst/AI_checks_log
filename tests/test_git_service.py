import subprocess
from pathlib import Path

import pytest

from app.git_service import build_pull_request_body, build_pull_request_title, repository_status


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


def test_pull_request_body_explains_failure_and_change() -> None:
    body = build_pull_request_body(
        "calculator.py",
        "Функция складывала значения вместо вычитания.",
        "return left + right",
        "return left - right",
        123,
    )

    assert "Что произошло" in body
    assert "Причина проблемы" in body
    assert "Доказательства" in body
    assert "Что изменено" in body
    assert "Проверка" in body
    assert "return left + right" in body
    assert "return left - right" in body
    assert "123" in body


def test_pull_request_body_includes_full_analysis() -> None:
    body = build_pull_request_body(
        "calculator.py", "Короткая причина", "old", "new", analysis="Подробный анализ CI с доказательствами"
    )

    assert "Полный анализ CI" in body
    assert "Подробный анализ CI с доказательствами" in body


def test_pull_request_body_is_not_empty_without_analysis() -> None:
    body = build_pull_request_body("calculator.py", "Исправить сложение", "old", "new")

    assert len(body) > 200
    assert "Причина проблемы" in body
    assert "Что изменено" in body


def test_pull_request_title_contains_file_and_reason() -> None:
    title = build_pull_request_title("calculator.py", "Функция складывала вместо вычитания")

    assert title == "fix: calculator.py"
    assert "складывала" not in title


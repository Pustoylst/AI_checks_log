"""Repository and GitHub CI operations with explicit-action boundaries."""

import json
import subprocess
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from app.config import Settings


class GitOperationError(RuntimeError):
    """Raised when a Git or GitHub operation cannot be completed."""


def _run_git(repo_root: str | Path, *args: str) -> str:
    """Run Git without a shell and return stdout."""

    try:
        result = subprocess.run(
            ["git", *args],
            cwd=Path(repo_root).resolve(),
            capture_output=True,
            text=True,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError) as error:
        detail = getattr(error, "stderr", "") or str(error)
        raise GitOperationError(detail.strip()) from error
    return result.stdout.strip()


def repository_status(repo_root: str | Path) -> dict[str, object]:
    """Return branch, remote and changed files for a local repository."""

    try:
        remote = _run_git(repo_root, "remote", "get-url", "origin")
    except GitOperationError:
        remote = None
    return {
        "branch": _run_git(repo_root, "branch", "--show-current"),
        "remote": remote,
        "changes": _run_git(repo_root, "status", "--short").splitlines(),
    }


def commit_and_push(repo_root: str | Path, paths: list[str], message: str, approved: bool) -> dict[str, str]:
    """Commit current changes and push only after explicit approval."""

    if not approved:
        raise PermissionError("Commit не выполнен: требуется явное подтверждение пользователя")
    if not message.strip():
        raise ValueError("Комментарий commit не может быть пустым")
    if not paths:
        raise ValueError("Для commit нужно явно указать изменяемые файлы")
    _run_git(repo_root, "add", "--", *paths)
    _run_git(repo_root, "commit", "-m", message.strip())
    _run_git(repo_root, "push", "origin", "HEAD")
    return {"message": message.strip(), "branch": _run_git(repo_root, "branch", "--show-current")}


def merge_branch(repo_root: str | Path, source_branch: str, target_branch: str, approved: bool) -> dict[str, str]:
    """Merge a local source branch into target only after explicit approval."""

    if not approved:
        raise PermissionError("Merge не выполнен: требуется явное подтверждение пользователя")
    if not source_branch or not target_branch or source_branch == target_branch:
        raise ValueError("Нужны разные source и target ветки")
    _run_git(repo_root, "checkout", target_branch)
    _run_git(repo_root, "pull", "--ff-only", "origin", target_branch)
    _run_git(repo_root, "merge", "--no-edit", source_branch)
    _run_git(repo_root, "push", "origin", target_branch)
    return {"source_branch": source_branch, "target_branch": target_branch}


def github_checks(settings: Settings, ref: str | None = None) -> dict[str, object]:
    """Read GitHub commit checks; return a clear error when integration is disabled."""

    if not settings.github_token or not settings.github_repository:
        raise ValueError("GITHUB_TOKEN и GITHUB_REPOSITORY не настроены")
    commit_ref = ref or settings.github_default_branch
    url = f"{settings.github_api_url.rstrip('/')}/repos/{settings.github_repository}/commits/{commit_ref}/check-runs"
    request = Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {settings.github_token.get_secret_value()}",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "directum-log-analyzer",
        },
    )
    try:
        with urlopen(request, timeout=20) as response:
            payload = json.load(response)
    except (HTTPError, URLError, TimeoutError) as error:
        raise GitOperationError(f"Не удалось получить CI-проверки GitHub: {error}") from error
    return {
        "ref": commit_ref,
        "total": payload.get("total_count", 0),
        "checks": [
            {
                "name": item.get("name"),
                "status": item.get("status"),
                "conclusion": item.get("conclusion"),
                "url": item.get("html_url"),
            }
            for item in payload.get("check_runs", [])
        ],
    }
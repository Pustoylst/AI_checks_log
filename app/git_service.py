"""Repository and GitHub CI operations with explicit-action boundaries."""

import json
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from app.config import Settings
from app.fixes import apply_approved_fix


class GitOperationError(RuntimeError):
    """Raised when a Git or GitHub operation cannot be completed."""


def normalize_github_repository(repository: str) -> str:
    """Convert a GitHub URL or owner/repository value to API path format."""

    value = repository.strip().rstrip("/")
    if value.startswith(("https://", "http://")):
        parsed = urlparse(value)
        value = parsed.path.strip("/")
    if value.endswith(".git"):
        value = value[:-4]
    if value.count("/") != 1 or any(not part for part in value.split("/")):
        raise ValueError("GITHUB_REPOSITORY должен быть в формате owner/repository или GitHub URL")
    return value


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


def create_pull_request(
    repo_root: str | Path,
    settings: Settings,
    path: str,
    explanation: str,
    old_text: str,
    new_text: str,
    base_branch: str,
    title: str,
    run_id: int | None,
    approved: bool,
) -> dict[str, str | int]:
    """Apply a proposal in an isolated branch and open a GitHub Pull Request."""

    if not approved:
        raise PermissionError("Pull Request не создан: требуется явное подтверждение пользователя")
    if not settings.github_token or not settings.github_repository:
        raise ValueError("GITHUB_TOKEN и GITHUB_REPOSITORY не настроены")
    if not base_branch.strip() or not title.strip():
        raise ValueError("Нужны base_branch и title")

    repository = normalize_github_repository(settings.github_repository)
    branch_name = f"agent/fix-{run_id or 'manual'}-{datetime.now():%Y%m%d%H%M%S}"
    repo_path = Path(repo_root).resolve()

    with tempfile.TemporaryDirectory(prefix="directum-agent-") as worktree:
        _run_git(repo_path, "fetch", "origin", base_branch)
        _run_git(repo_path, "worktree", "add", "-b", branch_name, worktree, f"origin/{base_branch}")
        try:
            apply_approved_fix(worktree, path, old_text, new_text, True)
            _run_git(worktree, "add", "--", path)
            _run_git(worktree, "config", "user.email", "directum-agent@users.noreply.github.com")
            _run_git(worktree, "config", "user.name", "Directum Agent")
            commit_message = title.strip()
            _run_git(worktree, "commit", "-m", commit_message)
            _run_git(worktree, "push", "-u", "origin", branch_name)
        finally:
            try:
                _run_git(repo_path, "worktree", "remove", "--force", worktree)
            except GitOperationError:
                pass

    body = (
        "## Анализ Directum Agent\n\n"
        f"{explanation.strip()}\n\n"
        "### Изменение\n"
        f"Файл: `{path}`\n\n"
        "```diff\n"
        f"- {old_text}\n+"
        f"+ {new_text}\n"
        "```\n\n"
        "Изменение создано только после явного подтверждения пользователя."
    )
    if run_id is not None:
        body = f"CI workflow run: {run_id}\n\n" + body
    return _create_github_pull_request(settings, repository, title.strip(), body, branch_name, base_branch)


def _create_github_pull_request(
    settings: Settings, repository: str, title: str, body: str, head: str, base: str
) -> dict[str, str | int]:
    """Create a GitHub Pull Request through the REST API."""

    payload = json.dumps({"title": title, "body": body, "head": head, "base": base}).encode("utf-8")
    request = Request(
        f"{settings.github_api_url.rstrip('/')}/repos/{repository}/pulls",
        data=payload,
        method="POST",
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {settings.github_token.get_secret_value()}",
            "Content-Type": "application/json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "directum-log-analyzer",
        },
    )
    try:
        with urlopen(request, timeout=30) as response:
            result = json.load(response)
    except (HTTPError, URLError, TimeoutError) as error:
        raise GitOperationError(f"Не удалось создать Pull Request: {error}") from error
    return {"number": result.get("number", 0), "url": result.get("html_url", ""), "branch": head}


def github_checks(settings: Settings, ref: str | None = None) -> dict[str, object]:
    """Read GitHub commit checks; return a clear error when integration is disabled."""

    if not settings.github_token or not settings.github_repository:
        raise ValueError("GITHUB_TOKEN и GITHUB_REPOSITORY не настроены")
    commit_ref = ref or settings.github_default_branch
    repository = normalize_github_repository(settings.github_repository or "")
    url = f"{settings.github_api_url.rstrip('/')}/repos/{repository}/commits/{commit_ref}/check-runs"
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
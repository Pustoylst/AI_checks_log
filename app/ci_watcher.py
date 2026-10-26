"""Read-only GitHub Actions watcher for failed workflow runs."""

import io
import json
import zipfile
from collections.abc import Callable
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from app.agent import analyze_log
from app.config import Settings
from app.git_service import GitOperationError, normalize_github_repository


def _github_request(settings: Settings, path: str, accept: str = "application/vnd.github+json") -> bytes:
    if not settings.github_token or not settings.github_repository:
        raise ValueError("GITHUB_TOKEN и GITHUB_REPOSITORY не настроены")
    request = Request(
        f"{settings.github_api_url.rstrip('/')}/repos/{normalize_github_repository(settings.github_repository or '')}{path}",
        headers={
            "Accept": accept,
            "Authorization": f"Bearer {settings.github_token.get_secret_value()}",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "directum-log-analyzer",
        },
    )
    try:
        with urlopen(request, timeout=30) as response:
            return response.read()
    except (HTTPError, URLError, TimeoutError) as error:
        raise GitOperationError(f"Ошибка запроса GitHub Actions: {error}") from error


def _failed_runs(settings: Settings, limit: int = 10) -> list[dict[str, object]]:
    payload = json.loads(_github_request(settings, f"/actions/runs?status=failure&per_page={limit}"))
    return payload.get("workflow_runs", [])


def _run_logs(settings: Settings, run_id: int) -> str:
    archive = _github_request(settings, f"/actions/runs/{run_id}/logs", "application/vnd.github+json")
    try:
        with zipfile.ZipFile(io.BytesIO(archive)) as zipped:
            chunks = []
            for name in zipped.namelist():
                if name.endswith("/"):
                    continue
                chunks.append(f"--- {name} ---\n{zipped.read(name).decode('utf-8', errors='replace')}")
            return "\n\n".join(chunks)
    except zipfile.BadZipFile as error:
        raise GitOperationError("GitHub не вернул архив логов workflow") from error


def _load_state(state_path: Path) -> set[int]:
    if not state_path.exists():
        return set()
    try:
        return {int(item) for item in json.loads(state_path.read_text(encoding="utf-8"))}
    except (OSError, ValueError, TypeError):
        return set()


def _save_state(state_path: Path, run_ids: set[int]) -> None:
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps(sorted(run_ids), ensure_ascii=True), encoding="utf-8")


def mark_fix_proposed(repo_root: str | Path, run_id: int) -> None:
    """Remember that a fix proposal was already requested for one CI run."""

    state_path = Path(repo_root) / ".ci-proposed-runs.json"
    proposed = _load_state(state_path)
    proposed.add(run_id)
    _save_state(state_path, proposed)


def scan_failed_runs(
    settings: Settings,
    repo_root: str | Path,
    state_path: str | Path = ".ci-watcher-state.json",
    analyzer: Callable[..., str] = analyze_log,
) -> list[dict[str, object]]:
    """Analyze unseen failed runs once; never writes to the Git repository."""

    state_file = Path(state_path)
    processed = _load_state(state_file)
    proposed = _load_state(Path(repo_root) / ".ci-proposed-runs.json")
    results: list[dict[str, object]] = []
    for run in _failed_runs(settings):
        run_id = int(run["id"])
        if run_id in processed or run_id in proposed:
            continue
        logs = _run_logs(settings, run_id)
        result = analyzer(
            {"workflow": run.get("name"), "run_id": run_id, "head_sha": run.get("head_sha"), "ci_logs": logs},
            repo_root=repo_root,
            settings=settings,
        )
        results.append(
            {
                "run_id": run_id,
                "workflow": run.get("name"),
                "branch": run.get("head_branch"),
                "url": run.get("html_url"),
                "analysis": result,
            }
        )
        processed.add(run_id)
    _save_state(state_file, processed)
    return results
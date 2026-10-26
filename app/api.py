"""HTTP API for Directum log analysis."""

import json
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, Query, UploadFile, status
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError

from app.agent import analyze_log, propose_fix
from app.ci_watcher import _run_logs, mark_fix_proposed, scan_failed_runs
from app.fixes import apply_approved_fix
from app.git_service import GitOperationError, create_pull_request, github_checks, repository_status
from app.schemas import ApplyFixRequest, ApplyFixResponse, AnalyzeResponse, FixProposal, LogPayload, PullRequestRequest

app = FastAPI(title="Directum Log Analyzer", version="0.1.0")
app.mount("/static", StaticFiles(directory=Path(__file__).parent.parent / "static"), name="static")


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    """Serve the local analysis workspace."""

    return FileResponse(Path(__file__).parent.parent / "static" / "index.html")


@app.get("/health")
def health() -> dict[str, str]:
    """Return a lightweight liveness response."""

    return {"status": "ok"}


@app.get("/repository/status")
def repository_status_endpoint(repo: str = Query(...)) -> dict[str, object]:
    """Return local Git status without changing the repository."""

    try:
        return repository_status(repo)
    except GitOperationError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from None


@app.get("/ci/checks")
def ci_checks_endpoint(ref: str | None = Query(default=None)) -> dict[str, object]:
    """Read GitHub CI checks for a branch or commit ref."""

    try:
        from app.config import get_settings

        return github_checks(get_settings(), ref)
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(error)) from None
    except GitOperationError as error:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(error)) from None


@app.post("/ci/scan")
def ci_scan_endpoint(repo: str = Query(...)) -> dict[str, object]:
    """Scan new failed GitHub Actions runs once without changing Git files."""

    try:
        from app.config import get_settings

        results = scan_failed_runs(get_settings(), repo, Path(repo) / ".ci-watcher-state.json")
        return {"results": results, "count": len(results)}
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(error)) from None
    except GitOperationError as error:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(error)) from None


@app.post("/ci/propose-fix", response_model=FixProposal)
def ci_propose_fix_endpoint(run_id: int = Query(...), repo: str = Query(...)) -> FixProposal:
    """Build a code-fix proposal directly from a failed GitHub Actions run."""

    try:
        from app.config import get_settings

        settings = get_settings()
        logs = _run_logs(settings, run_id)
        proposal = propose_fix({"run_id": run_id, "ci_logs": logs}, Path(repo))
        mark_fix_proposed(repo, run_id)
        return proposal
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(error)) from None
    except GitOperationError as error:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(error)) from None
    except Exception as error:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"Не удалось подготовить исправление: {error}") from None


@app.post("/github/pull-request")
def pull_request_endpoint(request: PullRequestRequest, repo: str = Query(...)) -> dict[str, str | int]:
    """Create an isolated agent branch, push it and open a Pull Request."""

    try:
        from app.config import get_settings

        return create_pull_request(
            repo,
            get_settings(),
            request.path,
            request.explanation,
            request.old_text,
            request.new_text,
            request.base_branch,
            request.title,
            request.run_id,
            request.approved,
        )
    except PermissionError as error:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(error)) from None
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(error)) from None
    except GitOperationError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from None


@app.post("/analyze", response_model=AnalyzeResponse)
async def analyze_endpoint(
    file: UploadFile = File(...),
    repo: str | None = Query(default=None, description="Optional repository root for code inspection"),
) -> AnalyzeResponse:
    """Validate an uploaded JSON log and send it to the analysis agent."""

    raw_data = await file.read()
    if not raw_data.strip():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Файл лога пуст")

    try:
        parsed_data = json.loads(raw_data)
        if parsed_data == {}:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Лог должен быть непустым JSON-объектом")
        payload = LogPayload.model_validate(parsed_data)
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Файл содержит невалидный JSON") from None
    except ValidationError as error:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=json.loads(error.json())) from None

    try:
        result = analyze_log(payload.model_dump(exclude_none=True), repo_root=Path(repo) if repo else None)
    except TimeoutError:
        raise HTTPException(status_code=status.HTTP_504_GATEWAY_TIMEOUT, detail="GigaChat не ответил вовремя") from None
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(error)) from None
    except Exception as error:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"Ошибка GigaChat: {error}") from None

    return AnalyzeResponse(result=result)


@app.post("/propose-fix", response_model=FixProposal)
async def propose_fix_endpoint(
    file: UploadFile = File(...),
    repo: str | None = Query(default=None, description="Repository root for code inspection"),
) -> FixProposal:
    """Generate a fix proposal without modifying any file."""

    if not repo:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Для предложения исправления нужен repo")
    raw_data = await file.read()
    try:
        payload = LogPayload.model_validate(json.loads(raw_data))
    except (json.JSONDecodeError, UnicodeDecodeError, ValidationError):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Нужен корректный JSON-лог") from None
    try:
        return propose_fix(payload.model_dump(exclude_none=True), Path(repo))
    except Exception as error:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"Не удалось подготовить исправление: {error}") from None


@app.post("/apply-fix", response_model=ApplyFixResponse)
def apply_fix_endpoint(request: ApplyFixRequest, repo: str = Query(...)) -> ApplyFixResponse:
    """Apply only the exact change explicitly approved by the user."""

    try:
        path, backup_path = apply_approved_fix(
            repo, request.path, request.old_text, request.new_text, request.approved
        )
    except PermissionError as error:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(error)) from None
    except (FileNotFoundError, ValueError) as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from None
    return ApplyFixResponse(path=path, backup_path=backup_path, message="Изменение применено; резервная копия создана")
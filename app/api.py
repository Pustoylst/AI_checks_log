"""HTTP API for Directum log analysis."""

from pathlib import Path

from fastapi import FastAPI, File, HTTPException, Query, UploadFile, status
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from app.log_input import MAX_UPLOAD_BYTES, parse_log, read_log_upload
from app.log_overview import (
    DEFAULT_OVERVIEW_BUDGET_CHARS,
    DEFAULT_OVERVIEW_MAX_BYTES,
    DEFAULT_OVERVIEW_MAX_FILES,
    LogOverviewError,
    build_overview,
)
from app.log_preprocess import DEFAULT_BUDGET_CHARS, DEFAULT_MAX_BYTES, LogPreprocessError, preprocess_file
from app.log_share import (
    LogShareError,
    LogSharePathError,
    LogShareUnavailableError,
    list_share_logs,
    resolve_share_log,
)

from app.agent import FixProposalError, analyze_log, propose_fix
from app.tools import validate_repository_root
from app.ci_watcher import _run_logs, mark_fix_proposed, scan_failed_runs
from app.fixes import apply_approved_fix
from app.git_service import (
    GitOperationError,
    build_pull_request_body,
    create_pull_request,
    github_checks,
    repository_status,
)
from app.schemas import (
    ApplyFixRequest,
    ApplyFixResponse,
    AnalyzeResponse,
    FixProposal,
    PullRequestRequest,
    ShareLogAnalyzeResponse,
    ShareLogPreprocessResponse,
    ShareLogsResponse,
    ShareOverviewAnalyzeRequest,
    ShareOverviewResponse,
)

app = FastAPI(title="Directum Log Analyzer", version="0.1.0")
app.mount("/static", StaticFiles(directory=Path(__file__).parent.parent / "static"), name="static")


def _repository_root(repo: str) -> Path:
    try:
        return validate_repository_root(repo)
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)) from None


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

    repo = str(_repository_root(repo))
    try:
        from app.config import get_settings

        state_dir = Path(get_settings().ci_state_dir).expanduser().resolve()
        repo_key = Path(repo).resolve().name
        results = scan_failed_runs(
            get_settings(),
            repo,
            state_dir / f"{repo_key}-processed.json",
            proposed_state_path=state_dir / f"{repo_key}-proposed.json",
        )
        return {"results": results, "count": len(results)}
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(error)) from None
    except GitOperationError as error:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(error)) from None


@app.post("/ci/propose-fix", response_model=FixProposal)
def ci_propose_fix_endpoint(run_id: int = Query(...), repo: str = Query(...)) -> FixProposal:
    """Build a code-fix proposal directly from a failed GitHub Actions run."""

    root = _repository_root(repo)
    try:
        from app.config import get_settings

        settings = get_settings()
        logs = _run_logs(settings, run_id)
        log_data = {"run_id": run_id, "ci_logs": logs}
        analysis = analyze_log(log_data, repo_root=root, settings=settings)
        proposal = propose_fix(log_data, root, settings=settings)
        proposal.analysis = analysis
        proposal.run_id = run_id
        proposal.description = build_pull_request_body(
            proposal.path,
            proposal.explanation,
            proposal.old_text,
            proposal.new_text,
            proposal.run_id,
            proposal.analysis,
        )
        state_dir = Path(settings.ci_state_dir).expanduser().resolve()
        mark_fix_proposed(repo, run_id, state_dir / f"{Path(repo).resolve().name}-proposed.json")
        return proposal
    except FixProposalError as error:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(error)) from None
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(error)) from None
    except GitOperationError as error:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(error)) from None
    except Exception:
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
            request.analysis,
            request.description,
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

    payload = await read_log_upload(file)

    root = _repository_root(repo) if repo else None
    try:
        result = analyze_log(payload, repo_root=root)
    except TimeoutError:
        raise HTTPException(status_code=status.HTTP_504_GATEWAY_TIMEOUT, detail="Анализ не завершился вовремя. Повторите попытку.") from None
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(error)) from None
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Не удалось выполнить анализ. Проверьте доступность ИИ-сервиса и повторите попытку.",
        ) from None

    return AnalyzeResponse(result=result)


@app.get("/logs/share/files", response_model=ShareLogsResponse)
def share_files_endpoint(limit: int | None = Query(default=None, ge=1, le=1000)) -> ShareLogsResponse:
    """List supported logs in the configured network share without copying them."""

    from app.config import get_settings

    settings = get_settings()
    effective_limit = min(limit or settings.log_share_max_files, settings.log_share_max_files)
    try:
        files = list_share_logs(
            settings.log_share_path,
            limit=effective_limit,
            scan_limit=settings.log_share_scan_limit,
        )
    except LogShareUnavailableError as error:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(error)) from None
    except LogShareError as error:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)) from None
    return ShareLogsResponse(root=settings.log_share_path, count=len(files), files=files)


def _preprocess_share_log(settings, name: str, focus: str):
    """Resolve and compact one share log without loading it into memory."""

    path, size = resolve_share_log(settings.log_share_path, name)
    return preprocess_file(
        path,
        source_name=name,
        size=size,
        focus=focus,
        budget_chars=getattr(settings, "log_preprocess_budget_chars", DEFAULT_BUDGET_CHARS),
        max_bytes=getattr(settings, "log_preprocess_max_bytes", DEFAULT_MAX_BYTES),
    )


def _preprocess_http_error(error: LogPreprocessError) -> HTTPException:
    message = str(error)
    status_code = (
        status.HTTP_503_SERVICE_UNAVAILABLE
        if "Не удалось прочитать" in message or "Не удалось получить" in message
        else status.HTTP_413_REQUEST_ENTITY_TOO_LARGE
    )
    return HTTPException(status_code=status_code, detail=message)


@app.get("/logs/share/preprocess", response_model=ShareLogPreprocessResponse)
def share_preprocess_endpoint(
    name: str = Query(..., description="Relative path inside the log share"),
    focus: str = Query(default="errors", pattern="^(errors|all)$"),
) -> ShareLogPreprocessResponse:
    """Return the compact report for a large log without calling the model."""

    from app.config import get_settings

    settings = get_settings()
    try:
        result = _preprocess_share_log(settings, name, focus)
    except LogShareUnavailableError as error:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(error)) from None
    except LogSharePathError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from None
    except LogPreprocessError as error:
        raise _preprocess_http_error(error) from None
    return ShareLogPreprocessResponse(source=name, report=result.report, stats=result.stats)


@app.post("/logs/share/overview", response_model=ShareOverviewResponse)
def share_overview_endpoint(
    focus: str = Query(default="errors", pattern="^(errors|all)$"),
    limit: int | None = Query(
        default=None,
        ge=0,
        le=5000,
        description="0 or omitted means all files up to LOG_OVERVIEW_MAX_FILES",
    ),
) -> ShareOverviewResponse:
    """Scan many share logs and return one aggregate report without the model.

    The scan is deliberately separate from model analysis: a multi-gigabyte
    share can take a while, and the user may want to inspect the aggregate
    before spending time on inference.
    """

    from app.config import get_settings

    settings = get_settings()
    try:
        result = build_overview(
            settings.log_share_path,
            focus=focus,
            limit=limit,
            max_files=getattr(settings, "log_overview_max_files", DEFAULT_OVERVIEW_MAX_FILES),
            max_bytes=getattr(settings, "log_overview_max_bytes", DEFAULT_OVERVIEW_MAX_BYTES),
            per_file_max_bytes=getattr(settings, "log_preprocess_max_bytes", DEFAULT_MAX_BYTES),
            budget_chars=getattr(settings, "log_overview_budget_chars", DEFAULT_OVERVIEW_BUDGET_CHARS),
            scan_limit=getattr(settings, "log_share_scan_limit", 5000),
        )
    except LogShareUnavailableError as error:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(error)) from None
    except LogOverviewError as error:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(error)) from None
    except LogShareError as error:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)) from None
    return ShareOverviewResponse(
        root=settings.log_share_path,
        report=result.report,
        stats=result.stats,
    )


@app.post("/logs/share/overview/analyze", response_model=AnalyzeResponse)
def share_overview_analyze_endpoint(
    request: ShareOverviewAnalyzeRequest,
    repo: str | None = Query(default=None, description="Optional repository root for code inspection"),
) -> AnalyzeResponse:
    """Send a previously built overview report to the local analysis agent."""

    from app.config import get_settings

    settings = get_settings()
    root = _repository_root(repo) if repo else None
    payload = {
        "log_format": "overview",
        "source": "all selected logs",
        "report": request.report,
    }
    if request.question:
        payload["question"] = request.question
    try:
        result = analyze_log(payload, repo_root=root, settings=settings)
    except TimeoutError:
        raise HTTPException(status_code=status.HTTP_504_GATEWAY_TIMEOUT, detail="Анализ не завершился вовремя. Повторите попытку.") from None
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(error)) from None
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Не удалось выполнить анализ. Проверьте доступность ИИ-сервиса и повторите попытку.",
        ) from None
    return AnalyzeResponse(result=result)


@app.get("/logs/share/file")
def share_file_endpoint(name: str = Query(..., description="Relative path inside the log share")) -> FileResponse:
    """Stream one log from the network share without a 1 MiB download limit."""

    from app.config import get_settings

    try:
        path, _ = resolve_share_log(get_settings().log_share_path, name)
    except LogShareUnavailableError as error:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(error)) from None
    except LogSharePathError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from None
    return FileResponse(path, media_type="application/octet-stream", filename=path.name)


@app.post("/logs/share/analyze", response_model=ShareLogAnalyzeResponse)
def share_analyze_endpoint(
    name: str = Query(..., description="Relative path inside the log share"),
    repo: str | None = Query(default=None, description="Optional repository root for code inspection"),
    focus: str = Query(default="errors", pattern="^(errors|all)$"),
    question: str | None = Query(default=None, max_length=2000, description="Optional follow-up question"),
) -> ShareLogAnalyzeResponse:
    """Analyze one log read directly from the network share.

    Small single-object ``.json`` files keep the old direct parsing. Everything
    else is streamed through the preprocessor so a 200 MB daily log becomes a
    bounded report instead of a request to load the whole file into memory.
    """

    from app.config import get_settings

    settings = get_settings()
    try:
        path, size = resolve_share_log(settings.log_share_path, name)
    except LogShareUnavailableError as error:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(error)) from None
    except LogSharePathError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from None

    preprocessed = False
    stats = None
    if path.suffix.lower() == ".json" and size <= MAX_UPLOAD_BYTES:
        try:
            raw = path.read_bytes()
        except OSError as error:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=f"Не удалось прочитать лог {name}: {error}",
            ) from None
        try:
            payload = parse_log(raw, path.name)
        except HTTPException as error:
            # Only valid multi-record JSONL may fall back to preprocessing.
            # Malformed JSON and invalid single-object payloads keep their errors.
            import json

            try:
                lines = [line for line in raw.decode("utf-8-sig").splitlines() if line.strip()]
                is_jsonl = len(lines) > 1 and all(isinstance(json.loads(line), dict) for line in lines)
            except (UnicodeDecodeError, ValueError):
                is_jsonl = False
            if error.status_code != 400 or not is_jsonl:
                raise
            preprocessed = True
    if preprocessed or path.suffix.lower() != ".json" or size > MAX_UPLOAD_BYTES:
        try:
            preprocessed_result = _preprocess_share_log(settings, name, focus)
        except LogShareUnavailableError as error:
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(error)) from None
        except LogSharePathError as error:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from None
        except LogPreprocessError as error:
            raise _preprocess_http_error(error) from None
        preprocessed = True
        stats = preprocessed_result.stats
        payload = {
            "log_format": "preprocessed",
            "source": name,
            "report": preprocessed_result.report,
        }
    if question:
        payload["question"] = question

    root = _repository_root(repo) if repo else None
    try:
        result = analyze_log(payload, repo_root=root, settings=settings)
    except TimeoutError:
        raise HTTPException(status_code=status.HTTP_504_GATEWAY_TIMEOUT, detail="Анализ не завершился вовремя. Повторите попытку.") from None
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(error)) from None
    except Exception as error:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Не удалось выполнить анализ. Проверьте доступность ИИ-сервиса и повторите попытку.",
        ) from None
    return ShareLogAnalyzeResponse(
        result=result,
        source=name,
        preprocessed=preprocessed,
        stats=stats,
    )


@app.post("/propose-fix", response_model=FixProposal)
async def propose_fix_endpoint(
    file: UploadFile = File(...),
    repo: str | None = Query(default=None, description="Repository root for code inspection"),
) -> FixProposal:
    """Generate a fix proposal without modifying any file."""

    if not repo:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Для предложения исправления нужен repo")
    payload = await read_log_upload(file)
    root = _repository_root(repo)
    try:
        from app.config import get_settings

        settings = get_settings()
        log_data = payload
        analysis = analyze_log(log_data, repo_root=root, settings=settings)
        proposal = propose_fix(log_data, root, settings=settings)
        proposal.analysis = analysis
        proposal.description = build_pull_request_body(
            proposal.path, proposal.explanation, proposal.old_text, proposal.new_text, analysis=proposal.analysis
        )
        return proposal
    except FixProposalError as error:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(error)) from None
    except Exception as error:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"Не удалось подготовить исправление: {error}") from None


@app.post("/apply-fix", response_model=ApplyFixResponse)
def apply_fix_endpoint(request: ApplyFixRequest, repo: str = Query(...)) -> ApplyFixResponse:
    """Apply only the exact change explicitly approved by the user."""

    try:
        path = apply_approved_fix(
            repo, request.path, request.old_text, request.new_text, request.approved
        )
    except PermissionError as error:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(error)) from None
    except (FileNotFoundError, ValueError) as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from None
    return ApplyFixResponse(path=path, message="Изменение применено")
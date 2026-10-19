"""HTTP API for Directum log analysis."""

import json
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, Query, UploadFile, status
from pydantic import ValidationError

from app.agent import analyze_log
from app.schemas import AnalyzeResponse, LogPayload

app = FastAPI(title="Directum Log Analyzer", version="0.1.0")


@app.get("/health")
def health() -> dict[str, str]:
    """Return a lightweight liveness response."""

    return {"status": "ok"}


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
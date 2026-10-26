import json
from pathlib import Path

from fastapi.testclient import TestClient

from app.api import app


client = TestClient(app)


def test_health() -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_frontend_is_served() -> None:
    response = client.get("/")

    assert response.status_code == 200
    assert "Разбор инцидента" in response.text
    assert client.get("/static/app.js").status_code == 200
    assert client.get("/static/styles.css").status_code == 200


def test_analyze_accepts_log_without_trace_id_or_repo_paths(monkeypatch) -> None:
    monkeypatch.setattr("app.api.analyze_log", lambda log_data, repo_root=None: "Анализ выполнен")
    response = client.post(
        "/analyze",
        files={"file": ("log.json", json.dumps({"message": "ошибка"}), "application/json")},
    )

    assert response.status_code == 200
    assert response.json() == {"result": "Анализ выполнен"}


def test_analyze_rejects_invalid_json() -> None:
    response = client.post(
        "/analyze",
        files={"file": ("log.json", "not-json", "application/json")},
    )

    assert response.status_code == 400
    assert "невалидный JSON" in response.json()["detail"]


def test_analyze_rejects_empty_log() -> None:
    response = client.post(
        "/analyze",
        files={"file": ("log.json", "{}", "application/json")},
    )

    assert response.status_code == 400
    assert "непустым JSON-объектом" in str(response.json()["detail"])


def test_apply_fix_requires_explicit_approval(tmp_path) -> None:
    response = client.post(
        "/apply-fix",
        params={"repo": str(tmp_path)},
        json={
            "path": "service.py",
            "explanation": "test",
            "old_text": "old",
            "new_text": "new",
            "approved": False,
        },
    )

    assert response.status_code == 403


def test_apply_fix_writes_only_approved_exact_change(tmp_path) -> None:
    (tmp_path / "service.py").write_text("old\n", encoding="utf-8")
    response = client.post(
        "/apply-fix",
        params={"repo": str(tmp_path)},
        json={
            "path": "service.py",
            "explanation": "test",
            "old_text": "old",
            "new_text": "new",
            "approved": True,
        },
    )

    assert response.status_code == 200
    assert (tmp_path / "service.py").read_text(encoding="utf-8") == "new\n"
    assert Path(response.json()["backup_path"]).exists()


def test_pull_request_endpoint_requires_approval(tmp_path) -> None:
    response = client.post(
        "/github/pull-request",
        params={"repo": str(tmp_path)},
        json={
            "approved": False,
            "path": "service.py",
            "explanation": "test",
            "old_text": "old",
            "new_text": "new",
        },
    )

    assert response.status_code == 403


def test_ci_scan_returns_new_failures(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr("app.api.scan_failed_runs", lambda settings, repo, state: [{"run_id": 7}])

    response = client.post("/ci/scan", params={"repo": str(tmp_path)})

    assert response.status_code == 200
    assert response.json() == {"results": [{"run_id": 7}], "count": 1}


def test_ci_propose_fix_uses_workflow_logs(monkeypatch, tmp_path) -> None:
    from app.schemas import FixProposal

    monkeypatch.setattr("app.api._run_logs", lambda settings, run_id: "AssertionError")
    monkeypatch.setattr(
        "app.api.propose_fix",
        lambda log_data, repo_root: FixProposal(
            path="service.py", explanation="Исправить тест", old_text="old", new_text="new"
        ),
    )
    response = client.post("/ci/propose-fix", params={"run_id": 7, "repo": str(tmp_path)})

    assert response.status_code == 200
    assert response.json()["path"] == "service.py"


def test_propose_fix_returns_reviewable_proposal(monkeypatch, tmp_path) -> None:
    from app.schemas import FixProposal

    monkeypatch.setattr(
        "app.api.propose_fix",
        lambda log_data, repo_root: FixProposal(
            path="service.py",
            explanation="Увеличить таймаут",
            old_text="TIMEOUT = 60",
            new_text="TIMEOUT = 120",
        ),
    )
    response = client.post(
        "/propose-fix",
        params={"repo": str(tmp_path)},
        files={"file": ("log.json", json.dumps({"message": "timeout"}), "application/json")},
    )

    assert response.status_code == 200
    assert response.json()["old_text"] == "TIMEOUT = 60"
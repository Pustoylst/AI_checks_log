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


def test_git_commit_endpoint_requires_approval(tmp_path) -> None:
    response = client.post(
        "/git/commit-push",
        params={"repo": str(tmp_path)},
        json={"message": "test", "approved": False},
    )

    assert response.status_code == 403


def test_git_merge_endpoint_requires_approval(tmp_path) -> None:
    response = client.post(
        "/git/merge",
        params={"repo": str(tmp_path)},
        json={"source_branch": "feature", "target_branch": "main", "approved": False},
    )

    assert response.status_code == 403


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
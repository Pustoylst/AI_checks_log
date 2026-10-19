import json

from fastapi.testclient import TestClient

from app.api import app


client = TestClient(app)


def test_health() -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


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
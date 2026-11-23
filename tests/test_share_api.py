import json
from types import SimpleNamespace

from fastapi.testclient import TestClient

from app.api import app


client = TestClient(app)


def _settings(share_root) -> SimpleNamespace:
    return SimpleNamespace(
        log_share_path=str(share_root),
        log_share_max_files=200,
        log_share_scan_limit=5000,
        log_preprocess_budget_chars=14000,
        log_preprocess_max_bytes=512 * 1024 * 1024,
        log_overview_budget_chars=16000,
        log_overview_max_files=1000,
        log_overview_max_bytes=3 * 1024 * 1024 * 1024,
    )


def test_share_files_lists_real_directory(monkeypatch, tmp_path) -> None:
    share = tmp_path / "Logs"
    share.mkdir()
    (share / "service.log").write_text("ERROR timeout", encoding="utf-8")
    monkeypatch.setattr("app.config.get_settings", lambda: _settings(share))

    response = client.get("/logs/share/files")

    assert response.status_code == 200
    body = response.json()
    assert body["root"] == str(share)
    assert body["count"] == 1
    assert body["files"][0]["path"] == "service.log"
    assert body["files"][0]["name"] == "service.log"


def test_share_files_reports_unavailable_share(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr("app.config.get_settings", lambda: _settings(tmp_path / "missing"))

    response = client.get("/logs/share/files")

    assert response.status_code == 503
    assert "недоступна" in response.json()["detail"]


def test_share_file_downloads_attachment(monkeypatch, tmp_path) -> None:
    share = tmp_path / "Logs"
    share.mkdir()
    (share / "service.log").write_text("ERROR timeout", encoding="utf-8")
    monkeypatch.setattr("app.config.get_settings", lambda: _settings(share))

    response = client.get("/logs/share/file", params={"name": "service.log"})

    assert response.status_code == 200
    assert response.content == b"ERROR timeout"
    assert "attachment" in response.headers["content-disposition"]


def test_share_file_rejects_traversal(monkeypatch, tmp_path) -> None:
    share = tmp_path / "Logs"
    share.mkdir()
    (tmp_path / "secret.log").write_text("secret", encoding="utf-8")
    monkeypatch.setattr("app.config.get_settings", lambda: _settings(share))

    response = client.get("/logs/share/file", params={"name": "../secret.log"})

    assert response.status_code == 404
    assert "вне сетевой папки" in response.json()["detail"]


def test_share_analyze_reads_file_and_returns_result(monkeypatch, tmp_path) -> None:
    share = tmp_path / "Logs"
    share.mkdir()
    (share / "service.json").write_text('{"message": "timeout"}', encoding="utf-8")
    monkeypatch.setattr("app.config.get_settings", lambda: _settings(share))
    monkeypatch.setattr(
        "app.api.analyze_log",
        lambda log_data, repo_root=None, settings=None: "Анализ из сетевой папки",
    )

    response = client.post("/logs/share/analyze", params={"name": "service.json"})

    assert response.status_code == 200
    assert response.json() == {
        "result": "Анализ из сетевой папки",
        "source": "service.json",
        "preprocessed": False,
        "stats": None,
    }


def test_share_analyze_rejects_invalid_json(monkeypatch, tmp_path) -> None:
    share = tmp_path / "Logs"
    share.mkdir()
    (share / "broken.json").write_text("not-json", encoding="utf-8")
    monkeypatch.setattr("app.config.get_settings", lambda: _settings(share))

    response = client.post("/logs/share/analyze", params={"name": "broken.json"})

    assert response.status_code == 400
    assert "невалидный JSON" in response.json()["detail"]


def _write_jsonl(path, rows) -> None:
    path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n",
        encoding="utf-8",
    )


def test_share_preprocess_returns_compact_report(monkeypatch, tmp_path) -> None:
    share = tmp_path / "Logs"
    share.mkdir()
    _write_jsonl(
        share / "service.log",
        [
            {"t": "2026-11-03 10:00:00", "l": "Info", "lg": "App", "mt": "started"},
            {
                "t": "2026-11-03 10:00:01",
                "l": "Error",
                "lg": "ServiceExceptionHandler",
                "mt": "RabbitMQ is not available",
                "ex": {"type": "BrokerNotAvailableException", "m": "RabbitMQ is not available"},
            },
        ],
    )
    monkeypatch.setattr("app.config.get_settings", lambda: _settings(share))

    response = client.get("/logs/share/preprocess", params={"name": "service.log"})

    assert response.status_code == 200
    body = response.json()
    assert body["source"] == "service.log"
    assert "RabbitMQ is not available" in body["report"]
    assert body["stats"]["format"] == "jsonl"
    assert body["stats"]["error_events"] == 1
    assert body["stats"]["report_chars"] == len(body["report"])


def test_share_preprocess_validates_focus(monkeypatch, tmp_path) -> None:
    share = tmp_path / "Logs"
    share.mkdir()
    (share / "service.log").write_text("ERROR", encoding="utf-8")
    monkeypatch.setattr("app.config.get_settings", lambda: _settings(share))

    response = client.get(
        "/logs/share/preprocess",
        params={"name": "service.log", "focus": "invalid"},
    )

    assert response.status_code == 422


def test_share_analyze_preprocesses_large_log(monkeypatch, tmp_path) -> None:
    share = tmp_path / "Logs"
    share.mkdir()
    _write_jsonl(
        share / "service.log",
        [
            {"t": "2026-11-03 10:00:00", "l": "Info", "lg": "App", "mt": "started"},
            {
                "t": "2026-11-03 10:00:01",
                "l": "Error",
                "lg": "ServiceExceptionHandler",
                "mt": "RabbitMQ is not available",
                "ex": {"type": "BrokerNotAvailableException", "m": "RabbitMQ is not available"},
            },
        ],
    )
    monkeypatch.setattr("app.config.get_settings", lambda: _settings(share))
    captured = {}

    def fake_analyze(log_data, repo_root=None, settings=None):
        captured["log_data"] = log_data
        return "Анализ выжимки"

    monkeypatch.setattr("app.api.analyze_log", fake_analyze)

    response = client.post(
        "/logs/share/analyze",
        params={"name": "service.log", "focus": "all"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["result"] == "Анализ выжимки"
    assert body["preprocessed"] is True
    assert body["stats"]["focus"] == "all"
    assert captured["log_data"]["log_format"] == "preprocessed"
    assert "RabbitMQ is not available" in captured["log_data"]["report"]


def test_share_file_download_streams_large_file(monkeypatch, tmp_path) -> None:
    share = tmp_path / "Logs"
    share.mkdir()
    content = b"x" * (2 * 1024 * 1024)
    (share / "large.log").write_bytes(content)
    monkeypatch.setattr("app.config.get_settings", lambda: _settings(share))

    response = client.get("/logs/share/file", params={"name": "large.log"})

    assert response.status_code == 200
    assert len(response.content) == len(content)
    assert response.headers["content-disposition"].startswith("attachment;")


def test_share_overview_returns_aggregate_report(monkeypatch, tmp_path) -> None:
    share = tmp_path / "Logs"
    share.mkdir()
    _write_jsonl(
        share / "AVP-EDU261-WS20.WebServer.2026-10-29.log",
        [
            {"t": "2026-10-29 10:00:00", "l": "Info", "lg": "App", "mt": "started"},
            {
                "t": "2026-10-29 10:00:01",
                "l": "Error",
                "lg": "ServiceExceptionHandler",
                "mt": "RabbitMQ is not available",
                "ex": {"type": "BrokerNotAvailableException", "m": "RabbitMQ is not available"},
            },
        ],
    )
    _write_jsonl(
        share / "AVP-EDU261-WS20.IntegrationService.2026-10-29.log",
        [
            {
                "t": "2026-10-29 11:00:00",
                "l": "Error",
                "lg": "ServiceExceptionHandler",
                "mt": "RabbitMQ is not available",
                "ex": {"type": "BrokerNotAvailableException", "m": "RabbitMQ is not available"},
            }
        ],
    )
    monkeypatch.setattr("app.config.get_settings", lambda: _settings(share))

    response = client.post("/logs/share/overview", params={"limit": 0})

    assert response.status_code == 200
    body = response.json()
    assert body["root"] == str(share)
    assert "RabbitMQ is not available" in body["report"]
    assert body["stats"]["files_scanned"] == 2
    assert body["stats"]["error_events"] == 2
    assert body["stats"]["top_error_signatures"][0]["count"] == 2


def test_share_overview_analyze_sends_overview_payload(monkeypatch) -> None:
    monkeypatch.setattr("app.config.get_settings", lambda: _settings("/unused"))
    captured = {}

    def fake_analyze(log_data, repo_root=None, settings=None):
        captured["log_data"] = log_data
        return "Общий анализ"

    monkeypatch.setattr("app.api.analyze_log", fake_analyze)

    response = client.post(
        "/logs/share/overview/analyze",
        json={
            "report": "# Общая сводка\n\nRabbitMQ is not available",
            "stats": {"files_scanned": 2},
            "question": "Что важнее всего исправить?",
        },
    )

    assert response.status_code == 200
    assert response.json() == {"result": "Общий анализ"}
    assert captured["log_data"]["log_format"] == "overview"
    assert captured["log_data"]["question"] == "Что важнее всего исправить?"
    assert "RabbitMQ" in captured["log_data"]["report"]


def test_share_analyze_accepts_follow_up_question(monkeypatch, tmp_path) -> None:
    share = tmp_path / "Logs"
    share.mkdir()
    _write_jsonl(
        share / "service.log",
        [
            {
                "t": "2026-11-03 10:00:01",
                "l": "Error",
                "lg": "ServiceExceptionHandler",
                "mt": "RabbitMQ is not available",
                "ex": {"type": "BrokerNotAvailableException", "m": "RabbitMQ is not available"},
            }
        ],
    )
    monkeypatch.setattr("app.config.get_settings", lambda: _settings(share))
    captured = {}

    def fake_analyze(log_data, repo_root=None, settings=None):
        captured["log_data"] = log_data
        return "Ответ на вопрос"

    monkeypatch.setattr("app.api.analyze_log", fake_analyze)

    response = client.post(
        "/logs/share/analyze",
        params={"name": "service.log", "question": "Почему RabbitMQ недоступен?"},
    )

    assert response.status_code == 200
    assert response.json()["result"] == "Ответ на вопрос"
    assert captured["log_data"]["question"] == "Почему RabbitMQ недоступен?"
    assert captured["log_data"]["log_format"] == "preprocessed"

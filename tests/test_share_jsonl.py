import json
from types import SimpleNamespace

import pytest

from fastapi.testclient import TestClient

from app.api import app


def test_small_jsonl_share_file_uses_preprocessor(monkeypatch, tmp_path):
    path = tmp_path / "service.json"
    rows = [{"l": "Info", "mt": "started"}, {"l": "Error", "mt": "broker unavailable"}]
    raw = "\n".join(json.dumps(row) for row in rows).encode("utf-8")
    path.write_bytes(raw)
    monkeypatch.setattr("app.config.get_settings", lambda: SimpleNamespace(log_share_path=str(tmp_path)))
    captured = []

    def analyze(payload, **kwargs):
        captured.append(payload)
        return "Анализ выполнен"

    monkeypatch.setattr("app.api.analyze_log", analyze)
    response = TestClient(app).post("/logs/share/analyze", params={"name": path.name})

    assert response.status_code == 200
    assert response.json()["preprocessed"] is True
    assert response.json()["stats"]["error_events"] == 1
    assert captured[0]["log_format"] == "preprocessed"
    assert "broker unavailable" in captured[0]["report"]
    assert path.read_bytes() == raw
    assert list(tmp_path.iterdir()) == [path]


@pytest.mark.parametrize("raw, expected_status", [
    (b'{"l":"Info"}\nnot json', 400),
    (b'{"l":"Info"}\n42', 400),
    (b'{}', 400),
    (b'[]', 422),
])
def test_invalid_share_json_is_not_reinterpreted(monkeypatch, tmp_path, raw, expected_status):
    path = tmp_path / "invalid.json"
    path.write_bytes(raw)
    monkeypatch.setattr("app.config.get_settings", lambda: SimpleNamespace(log_share_path=str(tmp_path)))

    def unexpected(*args, **kwargs):
        pytest.fail("Invalid JSON must not reach the model")

    monkeypatch.setattr("app.api.analyze_log", unexpected)
    response = TestClient(app).post("/logs/share/analyze", params={"name": path.name})
    assert response.status_code == expected_status
    assert path.read_bytes() == raw

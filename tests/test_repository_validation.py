import json

import pytest
from fastapi.testclient import TestClient

from app.api import app
from app.agent import FixProposalError
from app.tools import build_repository_tools


BAD_ROOT = r"C:\Users\Dima\Desktop\problems\C:\Users\Dima\Desktop\problems\agent-ci-fixture"


@pytest.mark.parametrize("endpoint", ["/ci/scan", "/ci/propose-fix", "/analyze", "/propose-fix"])
def test_invalid_root_rejected_before_model_or_github(monkeypatch, endpoint):
    def unexpected(*args, **kwargs):
        pytest.fail("Invalid root reached model or GitHub")

    monkeypatch.setattr("app.api._run_logs", unexpected)
    monkeypatch.setattr("app.api.scan_failed_runs", unexpected)
    monkeypatch.setattr("app.api.analyze_log", unexpected)
    monkeypatch.setattr("app.api.propose_fix", unexpected)
    response = TestClient(app).post(
        endpoint, params={"repo": BAD_ROOT, "run_id": 43871127066},
        files={"file": ("log.json", json.dumps({"message": "test failed"}), "application/json")},
    )
    assert response.status_code == 400
    assert "буква диска" in response.json()["detail"]


def test_missing_root_rejected_before_tools(tmp_path):
    with pytest.raises(ValueError, match="Папка репозитория не найдена"):
        build_repository_tools(tmp_path / "missing")


def test_ci_rejection_is_not_service_unavailable(monkeypatch, tmp_path):
    monkeypatch.setattr("app.api._run_logs", lambda *args: "AssertionError")
    monkeypatch.setattr("app.api.analyze_log", lambda *args, **kwargs: "analysis")

    def reject(*args, **kwargs):
        raise FixProposalError("old_text не совпадает; файлы не изменены")

    monkeypatch.setattr("app.api.propose_fix", reject)
    monkeypatch.setattr("app.api.mark_fix_proposed", lambda *args: pytest.fail("Rejected proposal marked ready"))
    response = TestClient(app).post("/ci/propose-fix", params={"repo": str(tmp_path), "run_id": 7})
    assert response.status_code == 422
    assert "old_text" in response.json()["detail"]

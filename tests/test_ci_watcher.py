import json
from pathlib import Path

from app.ci_watcher import mark_fix_proposed, scan_failed_runs
from app.config import Settings


def test_scan_failed_runs_analyzes_unseen_run_and_saves_state(monkeypatch, tmp_path: Path) -> None:
    settings = Settings(_env_file=None, github_token="test", github_repository="owner/repo")
    runs = [{"id": 42, "name": "Tests", "head_branch": "feature", "head_sha": "abc", "html_url": "https://run"}]
    analyzed = []

    monkeypatch.setattr("app.ci_watcher._failed_runs", lambda active_settings: runs)
    monkeypatch.setattr("app.ci_watcher._run_logs", lambda active_settings, run_id: "AssertionError: expected 1")

    def analyzer(log_data, repo_root, settings):
        analyzed.append(log_data)
        return "Причина найдена"

    state_path = tmp_path / "state.json"
    result = scan_failed_runs(settings, tmp_path, state_path, analyzer)

    assert result[0]["run_id"] == 42
    assert result[0]["analysis"] == "Причина найдена"
    assert analyzed[0]["ci_logs"] == "AssertionError: expected 1"
    assert json.loads(state_path.read_text(encoding="utf-8")) == [42]


def test_scan_failed_runs_does_not_repeat_processed_run(monkeypatch, tmp_path: Path) -> None:
    settings = Settings(_env_file=None, github_token="test", github_repository="owner/repo")
    state_path = tmp_path / "state.json"
    state_path.write_text("[42]", encoding="utf-8")
    monkeypatch.setattr("app.ci_watcher._failed_runs", lambda active_settings: [{"id": 42}])

    result = scan_failed_runs(settings, tmp_path, state_path, lambda *args, **kwargs: "must not run")

    assert result == []


def test_scan_failed_runs_skips_run_with_existing_fix_proposal(monkeypatch, tmp_path: Path) -> None:
    settings = Settings(_env_file=None, github_token="test", github_repository="owner/repo")
    mark_fix_proposed(tmp_path, 42)
    monkeypatch.setattr("app.ci_watcher._failed_runs", lambda active_settings: [{"id": 42}])

    result = scan_failed_runs(settings, tmp_path, tmp_path / "processed.json", lambda *args, **kwargs: "must not run")

    assert result == []
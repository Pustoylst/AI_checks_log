import json

import pytest

from app.log_overview import LogOverviewError, build_overview, service_from_path


def _jsonl(path, rows) -> None:
    path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n",
        encoding="utf-8",
    )


def _error(ts: str, message: str, exception: str = "BrokerNotAvailableException") -> dict:
    return {
        "t": ts,
        "l": "Error",
        "lg": "ServiceExceptionHandler",
        "mt": message,
        "ex": {"type": exception, "m": message},
    }


def test_overview_merges_signatures_across_files(tmp_path) -> None:
    share = tmp_path / "Logs"
    share.mkdir()
    _jsonl(
        share / "AVP-EDU261-WS20.WebServer.2026-10-29.log",
        [
            _error("2026-10-29 10:00:00", "RabbitMQ is not available for 12345"),
            {"t": "2026-10-29 10:00:01", "l": "Warn", "lg": "License", "mt": "License is invalid"},
        ],
    )
    _jsonl(
        share / "AVP-EDU261-WS20.IntegrationService.2026-10-29.log",
        [
            _error("2026-10-29 11:00:00", "RabbitMQ is not available for 67890"),
            _error("2026-10-29 11:00:01", "RabbitMQ is not available for 67891"),
        ],
    )

    result = build_overview(share, limit=0)

    stats = result.stats
    assert stats["files_scanned"] == 2
    assert stats["error_events"] == 3
    assert stats["warning_events"] == 1
    assert stats["error_signatures"] == 1
    top = stats["top_error_signatures"][0]
    assert top["exception_type"] == "BrokerNotAvailableException"
    assert top["count"] == 3
    assert top["file_count"] == 2
    assert top["service_count"] == 2
    assert "RabbitMQ is not available" in result.report
    assert "WebServer" in result.report
    assert "IntegrationService" in result.report
    assert "Файлы для детального анализа" in result.report
    assert result.truncated is False


def test_overview_limits_file_count_and_reports_more_files(tmp_path) -> None:
    share = tmp_path / "Logs"
    share.mkdir()
    for day in range(1, 4):
        _jsonl(
            share / f"AVP-EDU261-WS20.WebServer.2026-10-0{day}.log",
            [_error(f"2026-10-0{day} 10:00:00", f"failure {day}")],
        )

    result = build_overview(share, limit=1)

    assert result.stats["files_selected"] == 1
    assert result.stats["files_scanned"] == 1
    assert result.stats["has_more_files"] is True
    assert result.stats["truncated"] is True
    assert result.truncated is True


def test_overview_skips_oversized_file_and_keeps_others(tmp_path) -> None:
    share = tmp_path / "Logs"
    share.mkdir()
    _jsonl(
        share / "small.log",
        [_error("2026-10-29 10:00:00", "small failure")],
    )
    (share / "large.log").write_text("x" * 500, encoding="utf-8")

    result = build_overview(share, per_file_max_bytes=200)

    assert result.stats["files_scanned"] == 1
    assert result.stats["files_skipped"] == 1
    assert result.stats["skipped_count"] == 1
    assert "больше лимита" in result.stats["skipped"][0]["reason"]


def test_overview_raises_when_no_file_can_be_read(tmp_path) -> None:
    share = tmp_path / "Logs"
    share.mkdir()
    (share / "large.log").write_text("x" * 500, encoding="utf-8")

    with pytest.raises(LogOverviewError, match="ни одного лога"):
        build_overview(share, per_file_max_bytes=100)


def test_overview_respects_report_budget(tmp_path) -> None:
    share = tmp_path / "Logs"
    share.mkdir()
    rows = [
        _error(
            f"2026-10-29 10:00:{index:02d}",
            f"unique failure {chr(97 + index // 26)}{chr(97 + index % 26)} " + ("x" * 200),
        )
        for index in range(40)
    ]
    _jsonl(share / "AVP-EDU261-WS20.WebServer.2026-10-29.log", rows)

    result = build_overview(share, budget_chars=4000)

    assert result.stats["error_signatures"] == 40
    assert result.truncated is True
    assert len(result.report) <= 5000


def test_service_from_path_uses_service_before_date() -> None:
    assert service_from_path("AVP-EDU261-WS20.WebServer.2026-10-29.log") == "WebServer"
    assert (
        service_from_path("AVP-EDU261-WS20.IntegrationService.2026-10-29.log")
        == "IntegrationService"
    )
    assert service_from_path("plain.log") == "plain"

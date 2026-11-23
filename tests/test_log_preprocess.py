import json
from pathlib import Path

import pytest

from app.log_preprocess import LogPreprocessError, preprocess_file


def _jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n",
        encoding="utf-8",
    )


def test_preprocess_jsonl_groups_signatures_and_keeps_context(tmp_path) -> None:
    path = tmp_path / "service.log"
    rows = []
    for index in range(20):
        rows.append(
            {
                "t": f"2026-11-03 00:00:{index:02d}.000+05:00",
                "pid": "1+1",
                "l": "Trace",
                "lg": "Noise",
                "mt": f"noise {index}",
                "v": "1",
            }
        )
    rows.extend(
        [
            {
                "t": "2026-11-03 00:01:00.000+05:00",
                "pid": "1+1",
                "l": "Info",
                "lg": "Before",
                "mt": "before error",
                "v": "1",
            },
            {
                "t": "2026-11-03 00:01:01.000+05:00",
                "pid": "1+1",
                "l": "Error",
                "lg": "ServiceExceptionHandler",
                "mt": "RabbitMQ is not available for 12345",
                "tr": "trace-1",
                "ex": {
                    "type": "Sungero.Queue.BrokerNotAvailableException",
                    "m": "RabbitMQ is not available",
                    "stack": "stack line\n" * 500,
                },
                "v": "1",
            },
            {
                "t": "2026-11-03 00:01:02.000+05:00",
                "pid": "1+1",
                "l": "Info",
                "lg": "After",
                "mt": "after error",
                "v": "1",
            },
            {
                "t": "2026-11-03 00:01:03.000+05:00",
                "pid": "1+1",
                "l": "Error",
                "lg": "ServiceExceptionHandler",
                "mt": "RabbitMQ is not available for 67890",
                "tr": "trace-2",
                "ex": {
                    "type": "Sungero.Queue.BrokerNotAvailableException",
                    "m": "RabbitMQ is not available",
                    "stack": "stack line\n" * 500,
                },
                "v": "1",
            },
            {
                "t": "2026-11-03 00:01:04.000+05:00",
                "pid": "1+1",
                "l": "Warn",
                "lg": "License",
                "mt": "License is invalid for user 12345",
                "v": "1",
            },
        ]
    )
    _jsonl(path, rows)

    result = preprocess_file(path, budget_chars=14000)

    assert result.format == "jsonl"
    assert result.stats["lines"] == len(rows)
    assert result.stats["parsed"] == len(rows)
    assert result.stats["bad_lines"] == 0
    assert result.stats["levels"]["error"] == 2
    assert result.stats["levels"]["warn"] == 1
    assert result.stats["error_signatures"] == 1
    assert result.stats["error_events"] == 2
    assert result.stats["warning_signatures"] == 1
    assert result.stats["report_chars"] == len(result.report)
    assert len(result.report) <= 15000
    assert "ServiceExceptionHandler" in result.report
    assert "RabbitMQ is not available" in result.report
    assert "trace-1" in result.report
    assert "Контекст до" in result.report
    assert "before error" in result.report
    assert "Контекст после" in result.report
    assert "after error" in result.report
    assert "License is invalid" in result.report


def test_preprocess_respects_report_budget(tmp_path) -> None:
    path = tmp_path / "many-errors.log"
    rows = [
        {
            "t": f"2026-11-03 00:{index:02d}:00.000+05:00",
            "pid": "1+1",
            "l": "Error",
            "lg": f"Logger{index}",
            "mt": f"unique failure {index} " + ("x" * 200),
            "ex": {"type": "SomeException", "m": "failure", "stack": "s" * 3000},
            "v": "1",
        }
        for index in range(40)
    ]
    _jsonl(path, rows)

    result = preprocess_file(path, budget_chars=4000)

    assert result.truncated is True
    assert result.stats["truncated"] is True
    assert len(result.report) <= 5000
    assert result.stats["error_signatures"] == 40


def test_preprocess_text_fallback(tmp_path) -> None:
    path = tmp_path / "plain.log"
    path.write_text(
        "2026-11-03 10:00:00 INFO service started\n"
        "2026-11-03 10:00:01 ERROR timeout while calling API\n"
        "2026-11-03 10:00:02 INFO retrying\n",
        encoding="utf-8",
    )

    result = preprocess_file(path)

    assert result.format == "text"
    assert result.stats["levels"]["error"] == 1
    assert result.stats["error_signatures"] == 1
    assert "ERROR" in result.report
    assert "timeout while calling API" in result.report
    assert "retrying" in result.report


def test_preprocess_text_without_errors_keeps_sample_lines(tmp_path) -> None:
    path = tmp_path / "info.log"
    path.write_text(
        "2026-11-03 10:00:00 INFO service started\n"
        "2026-11-03 10:00:01 INFO waiting for jobs\n",
        encoding="utf-8",
    )

    result = preprocess_file(path)

    assert result.stats["levels"].get("error", 0) == 0
    assert "## Общая активность" in result.report
    assert "service started" in result.report
    assert "waiting for jobs" in result.report


def test_preprocess_counts_bad_json_lines(tmp_path) -> None:
    path = tmp_path / "broken.log"
    path.write_text(
        '{"t": "2026-11-03 10:00:00", "l": "Info", "lg": "App", "mt": "ok"}\n'
        "not json\n"
        '{"t": "2026-11-03 10:00:02", "l": "Error", "lg": "App", "mt": "boom"}\n',
        encoding="utf-8",
    )

    result = preprocess_file(path)

    assert result.format == "jsonl"
    assert result.stats["lines"] == 3
    assert result.stats["parsed"] == 2
    assert result.stats["bad_lines"] == 1
    assert "boom" in result.report


def test_preprocess_all_focus_adds_activity_section(tmp_path) -> None:
    path = tmp_path / "activity.log"
    _jsonl(
        path,
        [
            {"t": "2026-11-03 10:00:00", "l": "Info", "lg": "App", "mt": "started"},
            {"t": "2026-11-03 10:00:01", "l": "Trace", "lg": "App", "mt": "loop 1"},
            {"t": "2026-11-03 10:00:02", "l": "Trace", "lg": "App", "mt": "loop 2"},
        ],
    )

    result = preprocess_file(path, focus="all")

    assert "## Активность (все уровни)" in result.report
    assert "started" in result.report
    assert result.stats["focus"] == "all"


def test_preprocess_rejects_oversized_file(tmp_path) -> None:
    path = tmp_path / "large.log"
    path.write_text("x" * 100, encoding="utf-8")

    with pytest.raises(LogPreprocessError, match="больше"):
        preprocess_file(path, max_bytes=10)


def test_preprocess_rejects_invalid_focus_and_small_budget(tmp_path) -> None:
    path = tmp_path / "service.log"
    path.write_text("{}\n", encoding="utf-8")

    with pytest.raises(ValueError):
        preprocess_file(path, focus="unknown")
    with pytest.raises(ValueError):
        preprocess_file(path, budget_chars=100)

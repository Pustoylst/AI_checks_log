import os

import pytest

from app.log_share import (
    LogSharePathError,
    LogShareSizeError,
    LogShareUnavailableError,
    list_share_logs,
    read_share_log,
)


def test_list_share_logs_returns_supported_files_newest_first(tmp_path) -> None:
    root = tmp_path / "Logs"
    root.mkdir()
    old_log = root / "old.log"
    old_log.write_text("old", encoding="utf-8")
    nested = root / "2026-11-21"
    nested.mkdir()
    new_json = nested / "new.json"
    new_json.write_text('{"message": "new"}', encoding="utf-8")
    (root / "ignored.md").write_text("not a log", encoding="utf-8")
    hidden = root / ".cache"
    hidden.mkdir()
    (hidden / "hidden.log").write_text("hidden", encoding="utf-8")

    os.utime(old_log, (1000, 1000))
    os.utime(new_json, (2000, 2000))

    files = list_share_logs(root, limit=10, scan_limit=100)

    assert [item["path"] for item in files] == ["2026-11-21/new.json", "old.log"]
    assert files[0]["name"] == "new.json"
    assert files[0]["size"] == len('{"message": "new"}')
    assert files[0]["modified"]


def test_list_share_logs_respects_scan_limit(tmp_path) -> None:
    root = tmp_path / "Logs"
    root.mkdir()
    for name in ("a.log", "b.log", "c.log"):
        (root / name).write_text("x", encoding="utf-8")

    files = list_share_logs(root, limit=10, scan_limit=1)

    assert len(files) == 1


def test_list_share_logs_rejects_missing_share(tmp_path) -> None:
    with pytest.raises(LogShareUnavailableError):
        list_share_logs(tmp_path / "missing")


def test_read_share_log_reads_file(tmp_path) -> None:
    root = tmp_path / "Logs"
    root.mkdir()
    (root / "service.log").write_text("ERROR timeout", encoding="utf-8")

    raw, name = read_share_log(root, "service.log")

    assert raw == b"ERROR timeout"
    assert name == "service.log"


def test_read_share_log_rejects_path_outside_share(tmp_path) -> None:
    root = tmp_path / "Logs"
    root.mkdir()
    (tmp_path / "secret.log").write_text("secret", encoding="utf-8")

    with pytest.raises(LogSharePathError):
        read_share_log(root, "../secret.log")
    with pytest.raises(LogSharePathError):
        read_share_log(root, str(tmp_path / "secret.log"))


def test_read_share_log_rejects_unsupported_and_missing_files(tmp_path) -> None:
    root = tmp_path / "Logs"
    root.mkdir()
    (root / "notes.md").write_text("text", encoding="utf-8")

    with pytest.raises(LogSharePathError):
        read_share_log(root, "notes.md")
    with pytest.raises(LogSharePathError):
        read_share_log(root, "missing.log")


def test_read_share_log_rejects_oversized_file(tmp_path) -> None:
    root = tmp_path / "Logs"
    root.mkdir()
    (root / "large.log").write_text("0123456789", encoding="utf-8")

    with pytest.raises(LogShareSizeError):
        read_share_log(root, "large.log", max_bytes=4)

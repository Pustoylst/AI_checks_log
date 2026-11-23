"""Read-only access to a configured network log share.

The share is accessed with the credentials of the Windows account running the
service. Nothing is copied into the repository: files are listed, downloaded
on demand, streamed through the preprocessor, or parsed directly when small.
"""

import os
from datetime import datetime
from pathlib import Path

from app.log_input import MAX_UPLOAD_BYTES

ALLOWED_SUFFIXES = {".json", ".log", ".txt"}


class LogShareError(RuntimeError):
    """Base error for network log share operations."""


class LogShareUnavailableError(LogShareError):
    """The configured share is missing or cannot be read."""


class LogSharePathError(LogShareError):
    """The requested file is outside the share or is not a supported log."""


class LogShareSizeError(LogShareError):
    """The requested file is larger than the analysis limit."""


def _share_root(share_root: str | Path) -> Path:
    root = Path(share_root).expanduser()
    try:
        if not root.is_dir():
            raise LogShareUnavailableError(
                f"Сетевая папка логов недоступна: {share_root}. "
                "Проверьте путь, доступ к сети и права текущей учётной записи Windows."
            )
    except OSError as error:
        raise LogShareUnavailableError(
            f"Не удалось открыть сетевую папку логов {share_root}: {error}"
        ) from error
    return root


def _safe_share_path(root: Path, requested_path: str) -> Path:
    requested = requested_path.strip()
    if not requested:
        raise LogSharePathError("Не указан путь к логу в сетевой папке")

    try:
        resolved_root = root.resolve()
        candidate = (resolved_root / requested).resolve()
    except OSError as error:
        raise LogShareUnavailableError(
            f"Не удалось определить путь в сетевой папке логов: {error}"
        ) from error
    if candidate != resolved_root and resolved_root not in candidate.parents:
        raise LogSharePathError("Запрошенный файл находится вне сетевой папки логов")
    return candidate


def _relative_path(root: Path, file_path: Path) -> str:
    return file_path.relative_to(root).as_posix()


def list_share_logs(
    share_root: str | Path,
    limit: int = 200,
    scan_limit: int = 5000,
) -> list[dict[str, object]]:
    """List supported log files, newest first, without reading their content."""

    try:
        root = _share_root(share_root).resolve()
    except OSError as error:
        raise LogShareUnavailableError(
            f"Не удалось определить путь к сетевой папке логов: {error}"
        ) from error
    entries: list[dict[str, object]] = []
    scanned = 0
    limit = max(1, limit)
    scan_limit = max(1, scan_limit)

    try:
        for directory, directory_names, file_names in os.walk(root, followlinks=False):
            directory_names[:] = sorted(name for name in directory_names if not name.startswith("."))
            for file_name in file_names:
                if file_name.startswith("."):
                    continue

                scanned += 1
                if scanned > scan_limit:
                    break

                file_path = Path(directory) / file_name
                if file_path.suffix.lower() not in ALLOWED_SUFFIXES:
                    continue

                try:
                    stat = file_path.stat()
                except OSError:
                    continue

                entries.append(
                    {
                        "name": file_path.name,
                        "path": _relative_path(root, file_path),
                        "size": stat.st_size,
                        "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds"),
                        "modified_ts": stat.st_mtime,
                    }
                )
            if scanned > scan_limit:
                break
    except OSError as error:
        raise LogShareUnavailableError(
            f"Не удалось прочитать сетевую папку логов {share_root}: {error}"
        ) from error

    entries.sort(key=lambda item: item["modified_ts"], reverse=True)
    return [
        {
            "name": item["name"],
            "path": item["path"],
            "size": item["size"],
            "modified": item["modified"],
        }
        for item in entries[:limit]
    ]


def resolve_share_log(share_root: str | Path, requested_path: str) -> tuple[Path, int]:
    """Validate a log path inside the share and return its local path and size."""

    root = _share_root(share_root)
    file_path = _safe_share_path(root, requested_path)
    if file_path.suffix.lower() not in ALLOWED_SUFFIXES:
        raise LogSharePathError("Поддерживаются только файлы .json, .log и .txt")

    try:
        if not file_path.is_file():
            raise LogSharePathError(f"Лог не найден в сетевой папке: {requested_path}")
        size = file_path.stat().st_size
    except OSError as error:
        raise LogShareUnavailableError(
            f"Не удалось прочитать лог {requested_path}: {error}"
        ) from error
    return file_path, size


def read_share_log(
    share_root: str | Path,
    requested_path: str,
    max_bytes: int = MAX_UPLOAD_BYTES,
) -> tuple[bytes, str]:
    """Read one log from the share into memory and return its bytes and name."""

    file_path, size = resolve_share_log(share_root, requested_path)
    if size > max_bytes:
        raise LogShareSizeError(
            f"Лог превышает {max_bytes} байт. Выберите фрагмент вокруг ошибки"
        )

    try:
        with file_path.open("rb") as handle:
            raw = handle.read(max_bytes + 1)
    except OSError as error:
        raise LogShareUnavailableError(
            f"Не удалось прочитать лог {requested_path}: {error}"
        ) from error

    if len(raw) > max_bytes:
        raise LogShareSizeError(
            f"Лог превышает {max_bytes} байт. Выберите фрагмент вокруг ошибки"
        )
    return raw, file_path.name

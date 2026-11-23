"""Build one bounded overview from many Directum log files.

The share contains hundreds of daily logs (several gigabytes). Sending each
file to the model is impossible, and sending hundreds of separate reports is
also wasteful. This module streams every selected file without keeping it in
memory, merges error/warning signatures across files, and renders a single
compact report that the agent can analyse first. The per-file API remains the
drill-down step for a selected log.
"""

from __future__ import annotations

import json
import re
import time
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.log_preprocess import (
    DEFAULT_MAX_BYTES,
    ERROR_LEVELS,
    WARN_LEVELS,
    FileScan,
    LogPreprocessError,
    format_bytes,
    format_levels,
    normalize_message,
    scan_file,
)
from app.log_share import (
    LogSharePathError,
    LogShareUnavailableError,
    list_share_logs,
    resolve_share_log,
)

DEFAULT_OVERVIEW_BUDGET_CHARS = 16000
DEFAULT_OVERVIEW_MAX_FILES = 1000
DEFAULT_OVERVIEW_MAX_BYTES = 3 * 1024 * 1024 * 1024
MAX_GLOBAL_SIGNATURES = 5000
MAX_REPORT_ERRORS = 12
MAX_REPORT_WARNINGS = 6
MAX_REPORT_SERVICES = 10
MAX_REPORT_FILES = 12
MAX_REPORT_LOGGERS = 10
MAX_SAMPLE_FILES = 5
MAX_SAMPLE_SERVICES = 4
MAX_SAMPLE_LOGGERS = 3
MAX_STATS_ITEMS = 20
MAX_SKIPPED_ITEMS = 20

_DATE_RE = re.compile(r"[._-](\d{4}-\d{2}-\d{2})(?:[._-]|$)")


class LogOverviewError(RuntimeError):
    """The share cannot produce a usable overview."""


@dataclass
class GlobalSignature:
    """An error/warning signature merged across all scanned files."""

    level: str
    exception_type: str
    message: str
    count: int = 0
    loggers: list[str] = field(default_factory=list)
    file_count: int = 0
    sample_files: list[str] = field(default_factory=list)
    service_count: int = 0
    sample_services: list[str] = field(default_factory=list)
    first_ts: str = ""
    last_ts: str = ""
    sample: Any = None
    last_file: str = ""
    last_service: str = ""


@dataclass
class FileSummary:
    """Compact per-file counters used for drill-down ranking."""

    path: str
    name: str
    service: str
    size: int
    lines: int
    errors: int
    warnings: int
    fatal: int
    bad_lines: int
    first_ts: str
    last_ts: str
    format: str
    top_error: str = ""
    truncated: bool = False


@dataclass
class ServiceSummary:
    """Aggregated counters for one Directum service."""

    name: str
    files: int = 0
    bytes: int = 0
    lines: int = 0
    errors: int = 0
    warnings: int = 0
    fatal: int = 0
    top_error: str = ""
    top_error_count: int = 0


@dataclass
class OverviewResult:
    """A model-friendly overview plus machine-readable drill-down data."""

    report: str
    stats: dict[str, Any]
    truncated: bool


def service_from_path(path: str | Path) -> str:
    """Extract a service name from ``HOST.Service.YYYY-MM-DD.log``."""

    name = Path(path).name
    stem = name
    for suffix in (".log", ".json", ".txt"):
        if stem.lower().endswith(suffix):
            stem = stem[: -len(suffix)]
            break
    match = _DATE_RE.search(stem)
    prefix = stem[: match.start()] if match else stem
    parts = [part for part in re.split(r"[._-]+", prefix) if part]
    return parts[-1] if parts else (stem or name)


def _num(value: int) -> str:
    return f"{value:,}".replace(",", " ")


def _clip(value: Any, limit: int) -> str:
    text = "" if value is None else str(value)
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)] + "…"


def _sample_text(value: Any, limit: int = 700) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return _clip(value, limit)
    try:
        text = json.dumps(value, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        text = str(value)
    return _clip(text, limit)


def _top_error(scan: FileScan) -> str:
    errors = [item for item in scan.signatures.values() if item.level in ERROR_LEVELS]
    if not errors:
        return ""
    item = max(errors, key=lambda value: (value.count, value.last_ts))
    return _clip(item.message or item.exception_type, 220)


def _merge_signature(
    signatures: dict[tuple[str, str, str], GlobalSignature],
    signature,
    file_path: str,
    service: str,
) -> int:
    key = (signature.level, signature.exception_type, normalize_message(signature.message))
    merged = signatures.get(key)
    if merged is None:
        if len(signatures) >= MAX_GLOBAL_SIGNATURES:
            return signature.count
        merged = GlobalSignature(
            level=signature.level,
            exception_type=signature.exception_type,
            message=signature.message,
            sample=signature.sample,
        )
        signatures[key] = merged

    merged.count += signature.count
    if signature.logger and signature.logger not in merged.loggers and len(merged.loggers) < MAX_SAMPLE_LOGGERS:
        merged.loggers.append(signature.logger)
    if signature.first_ts and (not merged.first_ts or signature.first_ts < merged.first_ts):
        merged.first_ts = signature.first_ts
    if signature.last_ts and (not merged.last_ts or signature.last_ts > merged.last_ts):
        merged.last_ts = signature.last_ts
    if merged.sample is None and signature.sample is not None:
        merged.sample = signature.sample

    if merged.last_file != file_path:
        merged.file_count += 1
        if len(merged.sample_files) < MAX_SAMPLE_FILES:
            merged.sample_files.append(file_path)
        merged.last_file = file_path
    if merged.last_service != service:
        merged.service_count += 1
        if len(merged.sample_services) < MAX_SAMPLE_SERVICES:
            merged.sample_services.append(service)
        merged.last_service = service
    return 0


def _signature_sort_key(signature: GlobalSignature) -> tuple[int, int]:
    return (0 if signature.level == "fatal" else 1, -signature.count)


def _signature_stats(signature: GlobalSignature) -> dict[str, Any]:
    return {
        "level": signature.level,
        "exception_type": _clip(signature.exception_type, 300),
        "message": _clip(signature.message, 500),
        "count": signature.count,
        "file_count": signature.file_count,
        "service_count": signature.service_count,
        "loggers": list(signature.loggers),
        "services": list(signature.sample_services),
        "files": list(signature.sample_files),
        "first_timestamp": signature.first_ts,
        "last_timestamp": signature.last_ts,
    }


def _file_stats(item: FileSummary) -> dict[str, Any]:
    return {
        "path": item.path,
        "name": item.name,
        "service": item.service,
        "size": item.size,
        "lines": item.lines,
        "errors": item.errors,
        "warnings": item.warnings,
        "fatal": item.fatal,
        "bad_lines": item.bad_lines,
        "first_timestamp": item.first_ts,
        "last_timestamp": item.last_ts,
        "format": item.format,
        "top_error": item.top_error,
        "truncated": item.truncated,
    }


def _service_stats(item: ServiceSummary) -> dict[str, Any]:
    return {
        "name": item.name,
        "files": item.files,
        "bytes": item.bytes,
        "lines": item.lines,
        "errors": item.errors,
        "warnings": item.warnings,
        "fatal": item.fatal,
        "top_error": item.top_error,
    }


def _render_signature(index: int, signature: GlobalSignature) -> str:
    title = signature.level.upper() if signature.level != "other" else "OTHER"
    exception = _clip(signature.exception_type, 300) or "без типа исключения"
    lines = [
        f"### {index}. {title} · {exception} · {_num(signature.count)} событий · "
        f"{_num(signature.file_count)} файлов"
    ]
    if signature.message:
        lines.append(f"- Сообщение: {_clip(signature.message, 700)}")
    if signature.loggers:
        lines.append(f"- Логгеры: {', '.join(signature.loggers)}")
    if signature.sample_services:
        services = ", ".join(signature.sample_services)
        if signature.service_count > len(signature.sample_services):
            services += f" и ещё {signature.service_count - len(signature.sample_services)}"
        lines.append(f"- Сервисы: {services}")
    if signature.first_ts or signature.last_ts:
        lines.append(f"- Период: {signature.first_ts or '?'} — {signature.last_ts or '?'}")
    if signature.sample_files:
        files = ", ".join(signature.sample_files)
        if signature.file_count > len(signature.sample_files):
            files += f" и ещё {signature.file_count - len(signature.sample_files)}"
        lines.append(f"- Файлы: {files}")
    sample = _sample_text(signature.sample)
    if sample:
        lines.append(f"- Пример записи: {sample}")
    return "\n".join(lines)


def _render_service(service: ServiceSummary) -> str:
    parts = [
        f"- {service.name}: {_num(service.files)} файлов, "
        f"Error/Fatal {_num(service.errors + service.fatal)}, "
        f"Warn {_num(service.warnings)}, "
        f"{format_bytes(service.bytes)}, {_num(service.lines)} строк"
    ]
    if service.top_error:
        parts.append(f"; топ ошибка: {_clip(service.top_error, 220)}")
    return "".join(parts)


def _render_file(item: FileSummary) -> str:
    parts = [
        f"- {item.path}: Error/Fatal {_num(item.errors + item.fatal)}, "
        f"Warn {_num(item.warnings)}, {_num(item.lines)} строк"
    ]
    if item.top_error:
        parts.append(f"; топ ошибка: {_clip(item.top_error, 220)}")
    if item.truncated:
        parts.append("; файл прочитан не полностью")
    return "".join(parts)


def _render_overview(
    *,
    root: str,
    focus: str,
    files_selected: int,
    files_scanned: int,
    has_more_files: bool,
    bytes_selected: int,
    bytes_scanned: int,
    levels: Counter,
    formats: Counter,
    first_ts: str,
    last_ts: str,
    bad_lines: int,
    signatures: list[GlobalSignature],
    warnings: list[GlobalSignature],
    services: list[ServiceSummary],
    files: list[FileSummary],
    loggers: Counter,
    skipped: list[dict[str, str]],
    overflow_events: int,
    truncated_files: int,
    stopped_by_bytes: bool,
    stopped_by_files: bool,
    budget_chars: int,
) -> tuple[str, bool]:
    errors_count = sum(item.count for item in signatures)
    warnings_count = sum(item.count for item in warnings)
    files_with_errors = sum(1 for item in files if item.errors + item.fatal)
    truncated = bool(
        overflow_events
        or truncated_files
        or stopped_by_bytes
        or stopped_by_files
        or has_more_files
    )

    header = [
        "# Общая сводка по логам Directum",
        "",
        f"- Источник: {root}",
        f"- Охват: {_num(files_scanned)} из {_num(files_selected)} выбранных файлов"
        + (", в папке есть ещё файлы" if has_more_files else ""),
        f"- Размер выбранных файлов: {format_bytes(bytes_selected)}; прочитано: {format_bytes(bytes_scanned)}",
        f"- Строк: {_num(sum(levels.values()))}; ошибок разбора: {_num(bad_lines)}",
        f"- Период: {first_ts or '?'} — {last_ts or '?'}",
        f"- Уровни: {format_levels(levels)}",
        f"- Ошибки: {_num(errors_count)} событий в {_num(files_with_errors)} файлах; "
        f"предупреждения: {_num(warnings_count)} событий",
        f"- Форматы: {', '.join(f'{name} {count}' for name, count in formats.most_common()) or 'нет данных'}",
        f"- Режим: {'все уровни' if focus == 'all' else 'ошибки и предупреждения'}",
        "",
        "> Это агрегированная сводка по многим файлам, а не полные логи. "
        "Счётчики объединены по нормализованным сигнатурам; примеры записей сокращены. "
        "Исходные файлы не изменялись.",
    ]
    if stopped_by_bytes:
        header.append(
            f"> Охват остановлен по лимиту общего объёма ({format_bytes(bytes_scanned)})."
        )
    if stopped_by_files or has_more_files:
        header.append("> В сводку вошли не все файлы папки: выбран ограниченный охват.")

    parts = ["\n".join(header)]
    current_length = len(parts[0])

    def add(section: str) -> bool:
        nonlocal current_length
        if not section:
            return True
        extra = 2 + len(section)
        if current_length + extra > budget_chars:
            return False
        parts.append(section)
        current_length += extra
        return True

    if signatures:
        if not add(f"## Главные ошибки ({_num(len(signatures))} сигнатур, {_num(errors_count)} событий)"):
            truncated = True
        else:
            for index, signature in enumerate(signatures[:MAX_REPORT_ERRORS], start=1):
                if not add(_render_signature(index, signature)):
                    truncated = True
                    break
    else:
        if not add("## Главные ошибки\n\nОшибок уровня Error/Fatal не найдено."):
            truncated = True

    if warnings:
        if not add(
            f"## Главные предупреждения ({_num(len(warnings))} сигнатур, "
            f"{_num(warnings_count)} событий)"
        ):
            truncated = True
        else:
            for index, signature in enumerate(warnings[:MAX_REPORT_WARNINGS], start=1):
                if not add(_render_signature(index, signature)):
                    truncated = True
                    break

    if services:
        if not add("## Сервисы"):
            truncated = True
        else:
            for service in services[:MAX_REPORT_SERVICES]:
                if not add(_render_service(service)):
                    truncated = True
                    break

    interesting_files = [item for item in files if item.errors + item.fatal or item.warnings]
    if interesting_files:
        if not add("## Файлы для детального анализа"):
            truncated = True
        else:
            for item in interesting_files[:MAX_REPORT_FILES]:
                if not add(_render_file(item)):
                    truncated = True
                    break

    if focus == "all" and loggers:
        lines = ["## Топ логгеров по всем уровням"]
        for logger, count in loggers.most_common(MAX_REPORT_LOGGERS):
            lines.append(f"- {logger or 'без логгера'}: {_num(count)}")
        if not add("\n".join(lines)):
            truncated = True

    if skipped:
        lines = ["## Пропущенные файлы"]
        for item in skipped[:MAX_SKIPPED_ITEMS]:
            lines.append(f"- {item['path']}: {item['reason']}")
        if len(skipped) > MAX_SKIPPED_ITEMS:
            lines.append(f"- … и ещё {len(skipped) - MAX_SKIPPED_ITEMS}")
        if not add("\n".join(lines)):
            truncated = True

    notes: list[str] = []
    if overflow_events:
        notes.append(
            f"Не сгруппировано событий из-за лимита сигнатур: {_num(overflow_events)}."
        )
    if truncated_files:
        notes.append(f"Файлов, прочитанных не полностью: {_num(truncated_files)}.")
    if truncated:
        notes.append("Отчёт сокращён по бюджету; приоритет отдан частым ошибкам.")
    if notes:
        if not add("## Примечания\n\n" + "\n".join(f"- {item}" for item in notes)):
            truncated = True

    report = "\n\n".join(parts)
    hard_limit = budget_chars + 1000
    if len(report) > hard_limit:
        note = "\n\n> Отчёт принудительно обрезан."
        report = report[: max(0, hard_limit - len(note))] + note
        truncated = True
    return report, truncated


def build_overview(
    share_root: str | Path,
    *,
    focus: str = "errors",
    limit: int | None = None,
    max_files: int = DEFAULT_OVERVIEW_MAX_FILES,
    max_bytes: int = DEFAULT_OVERVIEW_MAX_BYTES,
    per_file_max_bytes: int = DEFAULT_MAX_BYTES,
    budget_chars: int = DEFAULT_OVERVIEW_BUDGET_CHARS,
    scan_limit: int = 5000,
) -> OverviewResult:
    """Scan selected share logs and merge them into one bounded report.

    Files are processed newest first. ``limit=0`` or ``None`` means the
    configured maximum. The total-byte limit prevents an accidental multi-hour
    scan if the share grows; per-file limits are applied separately.
    """

    if focus not in {"errors", "all"}:
        raise ValueError("focus должен быть 'errors' или 'all'")
    if budget_chars < 4000:
        raise ValueError("budget_chars должен быть не меньше 4000")
    if max_files < 1:
        raise ValueError("max_files должен быть положительным")
    if max_bytes < 1 or per_file_max_bytes < 1:
        raise ValueError("лимиты размера должны быть положительными")

    requested = max_files if limit is None or limit <= 0 else min(limit, max_files)
    listing = list_share_logs(
        share_root,
        limit=requested + 1,
        scan_limit=max(scan_limit, requested * 10),
    )
    has_more_files = len(listing) > requested
    files = listing[:requested]

    signatures: dict[tuple[str, str, str], GlobalSignature] = {}
    services: dict[str, ServiceSummary] = {}
    file_summaries: list[FileSummary] = []
    skipped: list[dict[str, str]] = []
    levels: Counter = Counter()
    formats: Counter = Counter()
    loggers: Counter = Counter()
    bytes_selected = sum(int(item.get("size") or 0) for item in files)
    bytes_scanned = 0
    bad_lines = 0
    overflow_events = 0
    truncated_files = 0
    first_ts = ""
    last_ts = ""
    stopped_by_bytes = False
    started = time.monotonic()

    for item in files:
        relative_path = str(item.get("path") or item.get("name") or "")
        declared_size = int(item.get("size") or 0)
        if bytes_scanned + declared_size > max_bytes:
            stopped_by_bytes = True
            break

        try:
            path, size = resolve_share_log(share_root, relative_path)
        except LogSharePathError as error:
            skipped.append({"path": relative_path, "reason": str(error)})
            continue
        except LogShareUnavailableError:
            raise
        if size > per_file_max_bytes:
            skipped.append(
                {
                    "path": relative_path,
                    "reason": f"больше лимита одного файла ({format_bytes(per_file_max_bytes)})",
                }
            )
            continue

        try:
            scan = scan_file(
                path,
                source_name=relative_path,
                size=size,
                focus=focus,
                max_bytes=per_file_max_bytes,
                collect_context=False,
                collect_activity=False,
            )
        except LogPreprocessError as error:
            skipped.append({"path": relative_path, "reason": str(error)})
            continue

        bytes_scanned += size
        bad_lines += scan.bad_lines
        levels.update(scan.levels)
        formats[scan.format] += 1
        loggers.update(scan.loggers)
        overflow_events += scan.overflow_signatures
        if scan.truncated:
            truncated_files += 1
        if scan.first_ts and (not first_ts or scan.first_ts < first_ts):
            first_ts = scan.first_ts
        if scan.last_ts and (not last_ts or scan.last_ts > last_ts):
            last_ts = scan.last_ts

        service_name = service_from_path(relative_path)
        errors = scan.levels.get("error", 0)
        fatal = scan.levels.get("fatal", 0)
        warnings = scan.levels.get("warn", 0)
        file_summary = FileSummary(
            path=relative_path,
            name=str(item.get("name") or Path(relative_path).name),
            service=service_name,
            size=size,
            lines=scan.lines,
            errors=errors,
            warnings=warnings,
            fatal=fatal,
            bad_lines=scan.bad_lines,
            first_ts=scan.first_ts,
            last_ts=scan.last_ts,
            format=scan.format,
            top_error=_top_error(scan),
            truncated=scan.truncated,
        )
        file_summaries.append(file_summary)

        service = services.get(service_name)
        if service is None:
            service = ServiceSummary(name=service_name)
            services[service_name] = service
        service.files += 1
        service.bytes += size
        service.lines += scan.lines
        service.errors += errors
        service.fatal += fatal
        service.warnings += warnings
        if file_summary.top_error and errors + fatal >= service.top_error_count:
            service.top_error = file_summary.top_error
            service.top_error_count = errors + fatal

        for signature in scan.signatures.values():
            overflow_events += _merge_signature(
                signatures, signature, relative_path, service_name
            )

    if not file_summaries:
        reasons = "; ".join(f"{item['path']}: {item['reason']}" for item in skipped[:5])
        raise LogOverviewError(
            "Не удалось прочитать ни одного лога для общей сводки."
            + (f" Причины: {reasons}" if reasons else "")
        )

    error_signatures = sorted(
        (item for item in signatures.values() if item.level in ERROR_LEVELS),
        key=_signature_sort_key,
    )
    warning_signatures = sorted(
        (item for item in signatures.values() if item.level in WARN_LEVELS),
        key=_signature_sort_key,
    )
    service_list = sorted(
        services.values(),
        key=lambda item: (item.errors + item.fatal, item.warnings, item.lines),
        reverse=True,
    )
    ranked_files = sorted(
        file_summaries,
        key=lambda item: (item.fatal, item.errors, item.warnings, item.size),
        reverse=True,
    )
    interesting_files = [item for item in ranked_files if item.errors + item.fatal or item.warnings]

    report, report_truncated = _render_overview(
        root=str(share_root),
        focus=focus,
        files_selected=len(files),
        files_scanned=len(file_summaries),
        has_more_files=has_more_files,
        bytes_selected=bytes_selected,
        bytes_scanned=bytes_scanned,
        levels=levels,
        formats=formats,
        first_ts=first_ts,
        last_ts=last_ts,
        bad_lines=bad_lines,
        signatures=error_signatures,
        warnings=warning_signatures,
        services=service_list,
        files=interesting_files,
        loggers=loggers,
        skipped=skipped,
        overflow_events=overflow_events,
        truncated_files=truncated_files,
        stopped_by_bytes=stopped_by_bytes,
        stopped_by_files=has_more_files,
        budget_chars=budget_chars,
    )
    truncated = bool(
        report_truncated
        or overflow_events
        or truncated_files
        or stopped_by_bytes
        or has_more_files
    )
    stats: dict[str, Any] = {
        "root": str(share_root),
        "focus": focus,
        "files_selected": len(files),
        "files_scanned": len(file_summaries),
        "files_skipped": len(skipped),
        "has_more_files": has_more_files,
        "bytes_selected": bytes_selected,
        "bytes_scanned": bytes_scanned,
        "lines": sum(levels.values()),
        "bad_lines": bad_lines,
        "levels": dict(levels),
        "formats": dict(formats),
        "first_timestamp": first_ts,
        "last_timestamp": last_ts,
        "error_events": levels.get("error", 0) + levels.get("fatal", 0),
        "warning_events": levels.get("warn", 0),
        "fatal_events": levels.get("fatal", 0),
        "files_with_errors": sum(1 for item in file_summaries if item.errors + item.fatal),
        "error_signatures": len(error_signatures),
        "warning_signatures": len(warning_signatures),
        "tracked_signatures": len(signatures),
        "overflow_events": overflow_events,
        "truncated_files": truncated_files,
        "truncated": truncated,
        "stopped_by_bytes": stopped_by_bytes,
        "max_files": max_files,
        "max_bytes": max_bytes,
        "per_file_max_bytes": per_file_max_bytes,
        "duration_seconds": round(time.monotonic() - started, 2),
        "report_chars": len(report),
        "top_error_signatures": [
            _signature_stats(item) for item in error_signatures[:MAX_STATS_ITEMS]
        ],
        "top_warning_signatures": [
            _signature_stats(item) for item in warning_signatures[:MAX_STATS_ITEMS]
        ],
        "top_files": [_file_stats(item) for item in ranked_files[:MAX_STATS_ITEMS]],
        "services": [_service_stats(item) for item in service_list[:MAX_STATS_ITEMS]],
        "skipped": skipped[:MAX_SKIPPED_ITEMS],
        "skipped_count": len(skipped),
    }
    return OverviewResult(report=report, stats=stats, truncated=truncated)

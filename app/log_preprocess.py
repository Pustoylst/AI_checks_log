"""Turn very large Directum logs into a compact, model-friendly report.

Directum service logs are JSON Lines: one JSON object per line with fields
such as ``t`` (timestamp), ``l`` (level), ``lg`` (logger), ``mt`` (message)
and ``ex`` (exception). A daily file can contain hundreds of thousands of
Trace/Info lines and only a handful of errors, so sending the raw file to an
8B model is both impossible and wasteful.

This module streams the file, aggregates counts and error signatures, keeps a
few representative entries with context, and renders a bounded report. The
original file is never modified.
"""

from __future__ import annotations

import json
import re
from collections import Counter, deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, TextIO

DEFAULT_BUDGET_CHARS = 14000
DEFAULT_MAX_BYTES = 512 * 1024 * 1024
MAX_SIGNATURES = 20
MAX_SAMPLE_CHARS = 3500
MAX_STACK_CHARS = 1800
MAX_CONTEXT_ENTRIES = 3
MAX_LINE_CHARS = 200_000
MAX_TRACKED_SIGNATURES = 500
MAX_ACTIVITY_KEYS = 5000
MAX_SCAN_LINES = 5_000_000

ERROR_LEVELS = {"error", "fatal"}
WARN_LEVELS = {"warn"}
INTERESTING_LEVELS = ERROR_LEVELS | WARN_LEVELS
LEVEL_ORDER = ("fatal", "error", "warn", "info", "debug", "trace", "other")

_GUID_RE = re.compile(
    r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b"
)
_HEX_RE = re.compile(r"\b0x[0-9a-fA-F]+\b")
_NUMBER_RE = re.compile(r"\b\d+(?:[.,]\d+)?\b")
_WHITESPACE_RE = re.compile(r"\s+")
_TEXT_LEVEL_RE = re.compile(
    r"\b(ERROR|ERR|WARN(?:ING)?|INFO|DEBUG|TRACE|FATAL|CRITICAL)\b", re.IGNORECASE
)
_TEXT_TS_RE = re.compile(
    r"^\s*\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}(?:[.,]\d+)?(?:[+-]\d{2}:?\d{2}|Z)?\s*"
)
_TEXT_TS_FIND_RE = re.compile(
    r"\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}(?:[.,]\d+)?(?:[+-]\d{2}:?\d{2}|Z)?"
)


class LogPreprocessError(RuntimeError):
    """The log cannot be preprocessed safely."""


@dataclass
class PreprocessResult:
    """A bounded report plus machine-readable statistics."""

    report: str
    stats: dict[str, Any]
    format: str
    truncated: bool


@dataclass
class SignatureSummary:
    level: str
    logger: str
    exception_type: str
    message: str
    count: int = 0
    first_ts: str = ""
    last_ts: str = ""
    trace_ids: list[str] = field(default_factory=list)
    sample: dict[str, Any] | str | None = None
    before: list[str] = field(default_factory=list)
    after: list[str] = field(default_factory=list)
    after_remaining: int = 0


@dataclass
class FileScan:
    source: str = ""
    format: str = ""
    encoding: str = ""
    size_bytes: int = 0
    lines: int = 0
    parsed: int = 0
    bad_lines: int = 0
    levels: Counter = field(default_factory=Counter)
    loggers: Counter = field(default_factory=Counter)
    error_loggers: Counter = field(default_factory=Counter)
    warn_loggers: Counter = field(default_factory=Counter)
    signatures: dict[tuple[str, str, str, str], SignatureSummary] = field(default_factory=dict)
    activity: Counter = field(default_factory=Counter)
    first_entries: list[str] = field(default_factory=list)
    last_entries: list[str] = field(default_factory=list)
    first_ts: str = ""
    last_ts: str = ""
    overflow_signatures: int = 0
    truncated: bool = False


def _as_text(value: Any) -> str:
    return "" if value is None else str(value)


def _truncate(text: Any, limit: int) -> str:
    value = _as_text(text)
    if len(value) <= limit:
        return value
    return value[: max(0, limit - 1)] + "…"


def _normalize_level(value: str) -> str:
    level = value.strip().lower()
    if level in {"warning", "warn"}:
        return "warn"
    if level in {"critical", "crit", "fatal"}:
        return "fatal"
    if level in {"error", "err"}:
        return "error"
    if level in {"info", "information"}:
        return "info"
    if level in {"debug"}:
        return "debug"
    if level in {"trace", "verbose"}:
        return "trace"
    return "other"


def _level(obj: dict[str, Any]) -> str:
    return _normalize_level(_as_text(obj.get("l") or obj.get("level") or ""))


def _logger(obj: dict[str, Any]) -> str:
    return _as_text(obj.get("lg") or obj.get("logger") or "")


def _message(obj: dict[str, Any]) -> str:
    return _as_text(obj.get("mt") or obj.get("message") or obj.get("m") or "")


def _timestamp(obj: dict[str, Any]) -> str:
    return _as_text(obj.get("t") or obj.get("timestamp") or "")


def _exception_info(obj: dict[str, Any]) -> tuple[str, str]:
    exception = obj.get("ex")
    if not isinstance(exception, dict):
        return "", ""
    return _as_text(exception.get("type")), _as_text(exception.get("m") or exception.get("message"))


def normalize_message(text: str) -> str:
    value = _GUID_RE.sub("<guid>", text)
    value = _HEX_RE.sub("<hex>", value)
    value = _NUMBER_RE.sub("<n>", value)
    value = _WHITESPACE_RE.sub(" ", value).strip()
    return value[:240]


def _signature_parts(obj: dict[str, Any]) -> tuple[tuple[str, str, str, str], str, str]:
    level = _level(obj)
    logger = _logger(obj)
    exception_type, exception_message = _exception_info(obj)
    message = _message(obj) or exception_message
    normalized = normalize_message(message)
    return (level, logger, exception_type, normalized), message, exception_type


def _trim_obj(obj: dict[str, Any]) -> dict[str, Any]:
    """Keep only fields useful for the report and bound large values."""

    result: dict[str, Any] = {}
    for key in ("t", "pid", "tr", "l", "lg", "mt", "un", "tn", "v"):
        value = obj.get(key)
        if value is not None and value != "":
            result[key] = _truncate(value, 1200 if key == "mt" else 200)

    exception = obj.get("ex")
    if isinstance(exception, dict):
        result["ex"] = {
            "type": _truncate(exception.get("type"), 300),
            "m": _truncate(exception.get("m") or exception.get("message"), 1000),
            "stack": _truncate(
                exception.get("stack") or exception.get("stackTrace"),
                MAX_STACK_CHARS * 2,
            ),
        }

    for key in ("args", "cust"):
        if obj.get(key) is not None:
            result[key] = _truncate(json.dumps(obj[key], ensure_ascii=False, default=str), 1200)
    return result


def _compact_entry(obj: dict[str, Any]) -> str:
    result: dict[str, Any] = {}
    for key in ("t", "pid", "tr", "l", "lg", "mt", "un", "tn"):
        value = obj.get(key)
        if value is not None and value != "":
            result[key] = _truncate(value, 300)
    exception = obj.get("ex")
    if isinstance(exception, dict):
        result["ex"] = {
            "type": _truncate(exception.get("type"), 200),
            "m": _truncate(exception.get("m") or exception.get("message"), 300),
        }
    return _truncate(json.dumps(result, ensure_ascii=False, default=str), 700)


def _detect_encoding(path: Path) -> str:
    try:
        with path.open("rb") as handle:
            sample = handle.read(65536)
    except OSError as error:
        raise LogPreprocessError(f"Не удалось прочитать файл: {error}") from error
    if sample.startswith((b"\xff\xfe", b"\xfe\xff")):
        return "utf-16"
    try:
        sample.decode("utf-8")
        return "utf-8-sig" if sample.startswith(b"\xef\xbb\xbf") else "utf-8"
    except UnicodeDecodeError:
        return "cp1251"


def _looks_like_jsonl(handle: TextIO) -> bool:
    for line in handle:
        stripped = line.strip()
        if not stripped:
            continue
        if not stripped.startswith("{"):
            return False
        try:
            return isinstance(json.loads(stripped), dict)
        except json.JSONDecodeError:
            return False
    return False


def _remember_entry(scan: FileScan, compact: str) -> None:
    if len(scan.first_entries) < 5:
        scan.first_entries.append(compact)
    scan.last_entries.append(compact)
    if len(scan.last_entries) > 5:
        scan.last_entries.pop(0)


def _record_signature(
    scan: FileScan,
    obj: dict[str, Any],
    previous: deque[str],
    pending_after: list[SignatureSummary],
    collect_context: bool,
) -> None:
    key, message, exception_type = _signature_parts(obj)
    signature = scan.signatures.get(key)
    if signature is None:
        if len(scan.signatures) >= MAX_TRACKED_SIGNATURES:
            scan.overflow_signatures += 1
            return
        signature = SignatureSummary(
            level=key[0],
            logger=key[1],
            exception_type=exception_type,
            message=message,
            sample=_trim_obj(obj),
            before=list(previous) if collect_context else [],
            after_remaining=MAX_CONTEXT_ENTRIES if collect_context else 0,
        )
        scan.signatures[key] = signature
        if collect_context:
            pending_after.append(signature)

    signature.count += 1
    timestamp = _timestamp(obj)
    if timestamp:
        if not signature.first_ts:
            signature.first_ts = timestamp
        signature.last_ts = timestamp
    trace_id = _as_text(obj.get("tr"))
    if trace_id and trace_id not in signature.trace_ids and len(signature.trace_ids) < 3:
        signature.trace_ids.append(trace_id)


def _scan_jsonl(
    handle: TextIO,
    focus: str,
    collect_context: bool = True,
    collect_activity: bool = True,
) -> FileScan:
    scan = FileScan()
    previous: deque[str] = deque(maxlen=MAX_CONTEXT_ENTRIES)
    pending_after: list[SignatureSummary] = []

    for line_number, raw_line in enumerate(handle, start=1):
        if line_number > MAX_SCAN_LINES:
            scan.truncated = True
            break
        line = raw_line.rstrip("\r\n")
        if not line.strip():
            continue
        scan.lines += 1
        if len(line) > MAX_LINE_CHARS:
            scan.bad_lines += 1
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            scan.bad_lines += 1
            continue
        if not isinstance(obj, dict):
            scan.bad_lines += 1
            continue

        scan.parsed += 1
        level = _level(obj)
        logger = _logger(obj)
        timestamp = _timestamp(obj)
        scan.levels[level] += 1
        scan.loggers[logger] += 1
        if timestamp:
            if not scan.first_ts:
                scan.first_ts = timestamp
            scan.last_ts = timestamp

        if level in ERROR_LEVELS:
            scan.error_loggers[logger] += 1
        elif level in WARN_LEVELS:
            scan.warn_loggers[logger] += 1

        if focus == "all" and collect_activity:
            message = _message(obj) or _exception_info(obj)[1]
            activity_key = (level, logger, normalize_message(message))
            if activity_key in scan.activity or len(scan.activity) < MAX_ACTIVITY_KEYS:
                scan.activity[activity_key] += 1

        if collect_context:
            compact = _compact_entry(obj)
            _remember_entry(scan, compact)
            for signature in list(pending_after):
                signature.after.append(compact)
                signature.after_remaining -= 1
                if signature.after_remaining <= 0:
                    pending_after.remove(signature)
            previous.append(compact)

        if level in INTERESTING_LEVELS:
            _record_signature(scan, obj, previous, pending_after, collect_context)

    return scan


def _text_level(line: str) -> str:
    match = _TEXT_LEVEL_RE.search(line)
    return _normalize_level(match.group(1)) if match else "other"


def _text_message(line: str) -> str:
    value = _TEXT_TS_RE.sub("", line, count=1)
    value = _TEXT_LEVEL_RE.sub("", value, count=1).strip(" :-[]\t")
    return value or line.strip()


def _scan_text(
    handle: TextIO,
    focus: str,
    collect_context: bool = True,
    collect_activity: bool = True,
) -> FileScan:
    scan = FileScan()
    previous: deque[str] = deque(maxlen=MAX_CONTEXT_ENTRIES)
    pending_after: list[SignatureSummary] = []

    for line_number, raw_line in enumerate(handle, start=1):
        if line_number > MAX_SCAN_LINES:
            scan.truncated = True
            break
        line = raw_line.rstrip("\r\n")
        if not line.strip():
            continue
        scan.lines += 1
        scan.parsed += 1

        level = _text_level(line)
        message = _text_message(line)
        timestamp_match = _TEXT_TS_FIND_RE.search(line)
        timestamp = timestamp_match.group(0) if timestamp_match else ""
        scan.levels[level] += 1
        scan.loggers[""] += 1
        if timestamp:
            if not scan.first_ts:
                scan.first_ts = timestamp
            scan.last_ts = timestamp
        if level in ERROR_LEVELS:
            scan.error_loggers[""] += 1
        elif level in WARN_LEVELS:
            scan.warn_loggers[""] += 1

        if focus == "all" and collect_activity:
            activity_key = (level, "", normalize_message(message))
            if activity_key in scan.activity or len(scan.activity) < MAX_ACTIVITY_KEYS:
                scan.activity[activity_key] += 1

        compact = _truncate(line, 700)
        if collect_context:
            _remember_entry(scan, compact)
            for signature in list(pending_after):
                signature.after.append(compact)
                signature.after_remaining -= 1
                if signature.after_remaining <= 0:
                    pending_after.remove(signature)

        if level in INTERESTING_LEVELS:
            key = (level, "", "", normalize_message(message))
            signature = scan.signatures.get(key)
            if signature is None:
                if len(scan.signatures) >= MAX_TRACKED_SIGNATURES:
                    scan.overflow_signatures += 1
                else:
                    signature = SignatureSummary(
                        level=level,
                        logger="",
                        exception_type="",
                        message=message,
                        sample=compact,
                        before=list(previous) if collect_context else [],
                        after_remaining=MAX_CONTEXT_ENTRIES if collect_context else 0,
                    )
                    scan.signatures[key] = signature
                    if collect_context:
                        pending_after.append(signature)
            if signature is not None:
                signature.count += 1
                if timestamp:
                    if not signature.first_ts:
                        signature.first_ts = timestamp
                    signature.last_ts = timestamp

        if collect_context:
            previous.append(compact)

    return scan


def _render_sample(signature: SignatureSummary) -> tuple[str, str]:
    if signature.sample is None:
        return "", ""
    if isinstance(signature.sample, str):
        return "text", _truncate(signature.sample, MAX_SAMPLE_CHARS)
    sample = _trim_obj(signature.sample)
    exception = sample.get("ex")
    if isinstance(exception, dict):
        exception["stack"] = _truncate(exception.get("stack"), MAX_STACK_CHARS)
    for key in ("args", "cust"):
        if key in sample:
            sample[key] = _truncate(sample[key], 800)
    return "json", _truncate(json.dumps(sample, ensure_ascii=False, default=str), MAX_SAMPLE_CHARS)


def _render_signature(index: int, signature: SignatureSummary) -> str:
    title = signature.level.upper() if signature.level != "other" else "OTHER"
    lines = [
        f"### {index}. {title} · {signature.logger or 'без логгера'} · {signature.count} событий"
    ]
    if signature.exception_type:
        lines.append(f"- Тип исключения: {_truncate(signature.exception_type, 400)}")
    if signature.message:
        lines.append(f"- Сообщение: {_truncate(signature.message, 700)}")
    if signature.first_ts or signature.last_ts:
        lines.append(f"- Период: {signature.first_ts or '?'} — {signature.last_ts or '?'}")
    if signature.trace_ids:
        lines.append(f"- Трассы: {', '.join(signature.trace_ids)}")

    language, sample = _render_sample(signature)
    if sample:
        lines.append(f"- Пример записи ({language}):")
        lines.append("```" + language)
        lines.append(sample)
        lines.append("```")
    if signature.before:
        lines.append("- Контекст до:")
        lines.extend(f"  - {_truncate(item, 500)}" for item in signature.before)
    if signature.after:
        lines.append("- Контекст после:")
        lines.extend(f"  - {_truncate(item, 500)}" for item in signature.after)
    return "\n".join(lines)


def _render_counter(title: str, counter: Counter, limit: int = 10) -> str:
    if not counter:
        return ""
    lines = [f"### {title}"]
    for name, count in counter.most_common(limit):
        lines.append(f"- {name or 'без логгера'}: {count}")
    return "\n".join(lines)


def _sorted_signatures(scan: FileScan, levels: set[str]) -> list[SignatureSummary]:
    items = [item for item in scan.signatures.values() if item.level in levels]
    # Stable two-pass sort: most frequent first, then the latest occurrence
    # first among signatures with the same count.
    items.sort(key=lambda item: item.last_ts, reverse=True)
    items.sort(key=lambda item: (0 if item.level == "fatal" else 1, -item.count))
    return items


def format_levels(levels: Counter) -> str:
    parts = []
    for level in LEVEL_ORDER:
        if levels.get(level):
            parts.append(f"{level} {levels[level]}")
    return ", ".join(parts) or "нет данных"


def format_bytes(size: int) -> str:
    if size < 1024:
        return f"{size} Б"
    if size < 1024 * 1024:
        return f"{size / 1024:.1f} КБ"
    if size < 1024 * 1024 * 1024:
        return f"{size / (1024 * 1024):.1f} МБ"
    return f"{size / (1024 * 1024 * 1024):.1f} ГБ"


def _build_report(
    scan: FileScan,
    source_name: str,
    size: int,
    focus: str,
    budget_chars: int,
    fmt: str,
    encoding: str,
) -> tuple[str, bool]:
    errors = _sorted_signatures(scan, ERROR_LEVELS)
    warnings = _sorted_signatures(scan, WARN_LEVELS)
    truncated = scan.truncated

    line_stats = (
        f"- Строк: {scan.lines}; JSON: {scan.parsed}; ошибок разбора: {scan.bad_lines}"
        if fmt == "jsonl"
        else f"- Строк: {scan.lines}"
    )
    header = [
        "# Выжимка лога Directum",
        "",
        f"- Источник: {source_name}",
        f"- Размер: {format_bytes(size)} ({size} байт)",
        f"- Формат: {fmt} ({encoding})",
        line_stats,
        f"- Период: {scan.first_ts or '?'} — {scan.last_ts or '?'}",
        f"- Уровни: {format_levels(scan.levels)}",
        f"- Сигнатуры: ошибки {len(errors)}, предупреждения {len(warnings)}",
        f"- Режим: {'все уровни' if focus == 'all' else 'ошибки и предупреждения'}",
        "",
        "> Это автоматическая выжимка, а не полный лог. Счётчики и сигнатуры "
        "агрегированы, длинные стеки сокращены. Исходный файл не изменялся.",
    ]

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

    if errors:
        if add(f"## Ошибки ({len(errors)} сигнатур, {sum(item.count for item in errors)} событий)"):
            for index, signature in enumerate(errors[:MAX_SIGNATURES], start=1):
                if not add(_render_signature(index, signature)):
                    truncated = True
                    break
    else:
        add("## Ошибки\n\nОшибок уровня Error/Fatal не найдено.")

    if warnings:
        if add(f"## Предупреждения ({len(warnings)} сигнатур, {sum(item.count for item in warnings)} событий)"):
            for index, signature in enumerate(warnings[:MAX_SIGNATURES], start=1):
                if not add(_render_signature(index, signature)):
                    truncated = True
                    break
    else:
        add("## Предупреждения\n\nПредупреждений уровня Warn не найдено.")

    if not errors and not warnings and focus != "all":
        samples: list[str] = []
        for entry in scan.first_entries[:3] + scan.last_entries[-2:]:
            if entry not in samples:
                samples.append(entry)
        if samples:
            lines = [
                "## Общая активность",
                "",
                "Ошибок и предупреждений не найдено. Примеры записей:",
            ]
            lines.extend(f"- {_truncate(entry, 500)}" for entry in samples)
            add("\n".join(lines))

    for title, counter, limit in (
        ("Топ логгеров по ошибкам", scan.error_loggers, 10),
        ("Топ логгеров по предупреждениям", scan.warn_loggers, 10),
        ("Топ логгеров по всем уровням", scan.loggers, 15),
    ):
        section = _render_counter(title, counter, limit=limit)
        if section:
            add(section)

    if focus == "all" and scan.activity:
        lines = ["## Активность (все уровни)"]
        for (level, logger, message), count in scan.activity.most_common(15):
            lines.append(f"- {level} · {logger or 'без логгера'}: {_truncate(message, 200)} — {count}")
        add("\n".join(lines))

    if scan.overflow_signatures:
        add(
            "## Примечание\n\n"
            f"Отслеживались первые {MAX_TRACKED_SIGNATURES} сигнатур; "
            f"ещё {scan.overflow_signatures} событий не сгруппированы."
        )

    if truncated:
        parts.append(
            "> Отчёт сокращён до настроенного лимита. Показаны самые частые сигнатуры; "
            "для полного контекста откройте исходный файл."
        )

    report = "\n\n".join(parts)
    hard_limit = budget_chars + 1000
    if len(report) > hard_limit:
        note = "\n\n> Отчёт принудительно обрезан."
        report = report[: max(0, hard_limit - len(note))] + note
        truncated = True
    return report, truncated


def scan_file(
    path: str | Path,
    source_name: str | None = None,
    size: int | None = None,
    focus: str = "errors",
    max_bytes: int = DEFAULT_MAX_BYTES,
    collect_context: bool = True,
    collect_activity: bool = True,
) -> FileScan:
    """Stream a log and return counters/signatures without rendering a report."""

    if focus not in {"errors", "all"}:
        raise ValueError("focus должен быть 'errors' или 'all'")

    log_path = Path(path)
    try:
        actual_size = size if size is not None else log_path.stat().st_size
    except OSError as error:
        raise LogPreprocessError(f"Не удалось получить размер лога: {error}") from error
    if actual_size > max_bytes:
        raise LogPreprocessError(
            f"Лог больше {max_bytes} байт. Выберите файл за меньший период или фрагмент."
        )

    encoding = _detect_encoding(log_path)
    try:
        with log_path.open("r", encoding=encoding, errors="replace") as handle:
            is_jsonl = _looks_like_jsonl(handle)
        with log_path.open("r", encoding=encoding, errors="replace") as handle:
            scan = (
                _scan_jsonl(handle, focus, collect_context, collect_activity)
                if is_jsonl
                else _scan_text(handle, focus, collect_context, collect_activity)
            )
    except OSError as error:
        raise LogPreprocessError(f"Не удалось прочитать лог: {error}") from error

    scan.source = source_name or log_path.name
    scan.format = "jsonl" if is_jsonl else "text"
    scan.encoding = encoding
    scan.size_bytes = actual_size
    return scan


def preprocess_file(
    path: str | Path,
    source_name: str | None = None,
    size: int | None = None,
    focus: str = "errors",
    budget_chars: int = DEFAULT_BUDGET_CHARS,
    max_bytes: int = DEFAULT_MAX_BYTES,
) -> PreprocessResult:
    """Stream a log file and return a bounded report. Never writes to the file."""

    if budget_chars < 4000:
        raise ValueError("budget_chars должен быть не меньше 4000")

    scan = scan_file(
        path,
        source_name=source_name,
        size=size,
        focus=focus,
        max_bytes=max_bytes,
        collect_context=True,
    )
    effective_name = scan.source
    fmt = scan.format
    encoding = scan.encoding
    actual_size = scan.size_bytes
    report, report_truncated = _build_report(
        scan, effective_name, actual_size, focus, budget_chars, fmt, encoding
    )
    errors = _sorted_signatures(scan, ERROR_LEVELS)
    warnings = _sorted_signatures(scan, WARN_LEVELS)
    stats: dict[str, Any] = {
        "source": effective_name,
        "format": fmt,
        "encoding": encoding,
        "size_bytes": actual_size,
        "lines": scan.lines,
        "parsed": scan.parsed,
        "bad_lines": scan.bad_lines,
        "levels": dict(scan.levels),
        "first_timestamp": scan.first_ts,
        "last_timestamp": scan.last_ts,
        "error_signatures": len(errors),
        "warning_signatures": len(warnings),
        "error_events": sum(item.count for item in errors),
        "warning_events": sum(item.count for item in warnings),
        "tracked_signatures": len(scan.signatures),
        "overflow_signatures": scan.overflow_signatures,
        "report_chars": len(report),
        "focus": focus,
        "truncated": scan.truncated or report_truncated,
    }
    return PreprocessResult(
        report=report,
        stats=stats,
        format=fmt,
        truncated=scan.truncated or report_truncated,
    )

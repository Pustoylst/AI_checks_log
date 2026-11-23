"""Build one overview report from many Directum logs without calling the model."""

import argparse
import sys
from pathlib import Path

from app.config import get_settings
from app.log_overview import LogOverviewError, build_overview
from app.log_share import LogShareError


def main() -> int:
    parser = argparse.ArgumentParser(description="Build an aggregate report from share logs")
    parser.add_argument("--limit", type=int, default=0, help="0 means all files up to the configured maximum")
    parser.add_argument("--focus", choices=("errors", "all"), default="errors")
    parser.add_argument("--budget-chars", type=int, default=None, help="Maximum report size")
    parser.add_argument("--max-files", type=int, default=None, help="Override LOG_OVERVIEW_MAX_FILES")
    parser.add_argument("--max-bytes", type=int, default=None, help="Override LOG_OVERVIEW_MAX_BYTES")
    parser.add_argument("--output", type=Path, help="Write the report to this file instead of stdout")
    args = parser.parse_args()

    settings = get_settings()
    try:
        result = build_overview(
            settings.log_share_path,
            focus=args.focus,
            limit=args.limit,
            max_files=args.max_files or settings.log_overview_max_files,
            max_bytes=args.max_bytes or settings.log_overview_max_bytes,
            per_file_max_bytes=settings.log_preprocess_max_bytes,
            budget_chars=args.budget_chars or settings.log_overview_budget_chars,
            scan_limit=settings.log_share_scan_limit,
        )
    except (OSError, LogShareError, LogOverviewError) as error:
        print(f"Ошибка общей сводки: {error}", file=sys.stderr)
        return 1

    if args.output:
        args.output.write_text(result.report, encoding="utf-8")
        print(f"Отчёт записан: {args.output}", file=sys.stderr)
    else:
        print(result.report)

    stats = result.stats
    print(
        "files={files_scanned}/{files_selected} bytes={bytes_scanned} lines={lines} "
        "errors={error_events} warnings={warning_events} report_chars={report_chars} "
        "truncated={truncated}".format(**stats),
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

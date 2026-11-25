"""Build a compact report from a large Directum log without calling the model."""

import argparse
import sys
from pathlib import Path

from app.config import get_settings
from app.log_preprocess import LogPreprocessError, preprocess_file
from app.log_share import LogShareError, resolve_share_log


def main() -> int:
    parser = argparse.ArgumentParser(description="Preprocess a large log into a compact report")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--share-file", help="Relative path inside LOG_SHARE_PATH")
    source.add_argument("--file", type=Path, help="Local log file")
    parser.add_argument("--focus", choices=("errors", "all"), default="errors")
    parser.add_argument("--budget-chars", type=int, default=None, help="Maximum report size")
    parser.add_argument("--output", type=Path, help="Write the report to this file instead of stdout")
    args = parser.parse_args()

    settings = get_settings()
    try:
        if args.share_file:
            path, size = resolve_share_log(settings.log_share_path, args.share_file)
            source_name = args.share_file
        else:
            path = args.file
            size = path.stat().st_size
            source_name = path.name
        result = preprocess_file(
            path,
            source_name=source_name,
            size=size,
            focus=args.focus,
            budget_chars=args.budget_chars or settings.log_preprocess_budget_chars,
            max_bytes=settings.log_preprocess_max_bytes,
        )
    except (OSError, LogShareError, LogPreprocessError) as error:
        print(f"Ошибка предобработки: {error}", file=sys.stderr)
        return 1

    if args.output:
        args.output.write_text(result.report, encoding="utf-8")
        print(f"Отчёт записан: {args.output}", file=sys.stderr)
    else:
        print(result.report)

    stats = result.stats
    print(
        "format={format} lines={lines} errors={error_events} warnings={warning_events} "
        "report_chars={report_chars} truncated={truncated}".format(**stats),
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

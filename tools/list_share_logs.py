"""Check access to the network log share and print the newest log files."""

import argparse

from app.config import get_settings
from app.log_share import LogShareError, list_share_logs


def main() -> int:
    parser = argparse.ArgumentParser(description="List logs in the configured network share")
    parser.add_argument("--limit", type=int, default=50, help="Maximum number of files to print")
    args = parser.parse_args()

    settings = get_settings()
    print(f"share={settings.log_share_path}")
    try:
        files = list_share_logs(
            settings.log_share_path,
            limit=max(1, min(args.limit, settings.log_share_max_files)),
            scan_limit=settings.log_share_scan_limit,
        )
    except LogShareError as error:
        print(f"Ошибка доступа к сетевой папке: {error}")
        return 1

    if not files:
        print("Подходящих файлов .json/.log/.txt не найдено.")
        return 0

    for item in files:
        print(f"{item['modified']}  {item['size']:>10}  {item['path']}")
    print(f"Всего показано: {len(files)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

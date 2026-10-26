"""Watch failed GitHub Actions runs and print agent analyses."""

import argparse
import time
from pathlib import Path

from app.ci_watcher import scan_failed_runs
from app.config import get_settings


def main() -> None:
    parser = argparse.ArgumentParser(description="Watch failed GitHub Actions runs")
    parser.add_argument("--repo", type=Path, required=True, help="Local repository root for code inspection")
    parser.add_argument("--state", type=Path, default=Path(".ci-watcher-state.json"))
    parser.add_argument("--once", action="store_true", help="Scan once and exit")
    args = parser.parse_args()
    settings = get_settings()

    while True:
        results = scan_failed_runs(settings, args.repo, args.state)
        for result in results:
            print(f"\n[{result['workflow']}] run {result['run_id']} ({result['url']})")
            print(result["analysis"])
            print("Предложение исправления и Git-операции требуют отдельного подтверждения пользователя.")
        if args.once:
            return
        time.sleep(settings.ci_poll_interval_seconds)


if __name__ == "__main__":
    main()
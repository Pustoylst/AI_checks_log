"""Watch failed GitHub Actions runs and print agent analyses."""

import argparse
import time
from pathlib import Path

from app.ci_watcher import scan_failed_runs
from app.config import get_settings


def main() -> None:
    parser = argparse.ArgumentParser(description="Watch failed GitHub Actions runs")
    parser.add_argument("--repo", type=Path, required=True, help="Local repository root for code inspection")
    parser.add_argument("--state", type=Path, default=None)
    parser.add_argument("--once", action="store_true", help="Scan once and exit")
    args = parser.parse_args()
    settings = get_settings()
    state_dir = Path(settings.ci_state_dir).expanduser().resolve()
    repo_key = args.repo.resolve().name
    state_path = args.state or state_dir / f"{repo_key}-processed.json"
    proposed_state_path = state_dir / f"{repo_key}-proposed.json"

    while True:
        results = scan_failed_runs(settings, args.repo, state_path, proposed_state_path=proposed_state_path)
        for result in results:
            print(f"\n[{result['workflow']}] run {result['run_id']} ({result['url']})")
            print(result["analysis"])
            print("Предложение исправления и Git-операции требуют отдельного подтверждения пользователя.")
        if args.once:
            return
        time.sleep(settings.ci_poll_interval_seconds)


if __name__ == "__main__":
    main()
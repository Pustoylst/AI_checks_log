"""Run the log analysis agent against a JSON file from the command line."""

import argparse
import json
from pathlib import Path

from app.agent import analyze_log


def main() -> None:
    parser = argparse.ArgumentParser(description="Analyze a Directum JSON log")
    parser.add_argument("log_file", type=Path)
    parser.add_argument("--repo", type=Path, default=None)
    args = parser.parse_args()

    log_data = json.loads(args.log_file.read_text(encoding="utf-8"))
    print(analyze_log(log_data, repo_root=args.repo))


if __name__ == "__main__":
    main()
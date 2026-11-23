"""Run event-handler regressions with Node when available (no npm packages)."""
import shutil
import subprocess
from pathlib import Path

import pytest


def test_overview_event_handlers():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js is required for frontend event-handler checks")
    result = subprocess.run(
        [node, str(Path(__file__).with_name("frontend_events.cjs"))],
        capture_output=True, timeout=15,
    )
    assert result.returncode == 0, (result.stdout + result.stderr).decode("utf-8", errors="replace")

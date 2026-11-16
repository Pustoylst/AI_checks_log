"""Opt-in real Ollama smoke check; only temporary fixture files are changed.

Run: python -m tools.verify_local_model
No GitHub requests are made. Requires the configured local model to be installed.
"""

import ast
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from time import perf_counter
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.api import app
from app.config import get_settings
from app.tools import build_repository_tools


def main() -> None:
    settings = get_settings()
    calls: list[str] = []

    def traced_tools(root):
        tools = build_repository_tools(root)
        for item in tools:
            original = item.func
            name = item.name

            def traced(*args, _original=original, _name=name, **kwargs):
                calls.append(_name)
                return _original(*args, **kwargs)

            item.func = traced
        return tools

    with TemporaryDirectory(prefix="qwen-smoke-") as directory:
        root = Path(directory)
        source = root / "calculator.py"
        original = "def subtract(left, right):\n    return left + right\n"
        source.write_text(original, encoding="utf-8")
        log = json.dumps({
            "level": "ERROR",
            "message": "AssertionError: subtract(7, 2) returned 9; expected 5",
            "file": "calculator.py",
            "symbol": "subtract",
        }).encode()
        client = TestClient(app)
        params = {"repo": str(root)}
        with patch("app.agent.build_repository_tools", side_effect=traced_tools):
            start = perf_counter()
            response = client.post("/analyze", params=params,
                                   files={"file": ("log.json", log, "application/json")})
            assert response.status_code == 200, response.text
            result = response.json()["result"]
            assert result.strip(), "Empty analysis"
            assert "read_git_file" in calls, f"No source read: {calls}; response={result}"
            assert "calculator.py" in result, result
            print(f"PASS analysis: model={settings.ollama_model}, seconds={perf_counter()-start:.1f}, tools={calls}")
            print(result)
            calls.clear()
            start = perf_counter()
            response = client.post("/propose-fix", params=params,
                                   files={"file": ("log.json", log, "application/json")})
            assert response.status_code == 200, response.text
            proposal = response.json()
            assert "read_git_file" in calls, f"No source read: {calls}"
            assert source.read_text(encoding="utf-8") == original, "Proposal changed source"
            assert proposal["path"] == "calculator.py", proposal
            assert proposal["old_text"] and original.count(proposal["old_text"]) == 1, proposal
            updated = original.replace(proposal["old_text"], proposal["new_text"], 1)
            # Inspect syntax only: never execute model-generated code.
            tree = ast.parse(updated)
            function = tree.body[0]
            assert isinstance(function, ast.FunctionDef) and function.name == "subtract", proposal
            assert len(function.body) == 1 and isinstance(function.body[0], ast.Return), proposal
            expression = function.body[0].value
            assert isinstance(expression, ast.BinOp) and isinstance(expression.op, ast.Sub), proposal
            assert isinstance(expression.left, ast.Name) and expression.left.id == "left", proposal
            assert isinstance(expression.right, ast.Name) and expression.right.id == "right", proposal
            print(f"PASS proposal: seconds={perf_counter()-start:.1f}, tools={calls}; source unchanged")
            denied = client.post("/apply-fix", params=params, json={**proposal, "approved": False})
            assert denied.status_code == 403, denied.text
            assert source.read_text(encoding="utf-8") == original
            applied = client.post("/apply-fix", params=params, json={**proposal, "approved": True})
            assert applied.status_code == 200, applied.text
            assert source.read_text(encoding="utf-8") == updated
            assert Path(applied.json()["backup_path"]).read_text(encoding="utf-8") == original
            print("PASS approval: denied without consent; applied with backup in temporary fixture only")


if __name__ == "__main__":
    main()

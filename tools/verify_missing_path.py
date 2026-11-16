"""Real local-model proposal check with a misleading analysis path; no working files changed."""
import ast
from pathlib import Path
from tempfile import TemporaryDirectory
from time import perf_counter

from app.agent import propose_fix


def main():
    with TemporaryDirectory(prefix="qwen-path-") as directory:
        root = Path(directory)
        original = 'def subtract(left: int, right: int) -> int:\n    return left + right\n'
        source = root / "calculator.py"
        source.write_text(original, encoding="utf-8")
        start = perf_counter()
        result = propose_fix({
            "log": "test_subtracts_numbers: subtract(5, 4) returned 9; expected 1. test_subtracts_negative_numbers: subtract(-2, 3) returned 1; expected -5",
            "analysis": "Example: src/math_operations.py contains def subtract(a, b): return a + b. Replace with a - b. This path has not been verified.",
        }, root)
        assert result.path == "calculator.py", result
        assert original.count(result.old_text) == 1, result
        updated = original.replace(result.old_text, result.new_text, 1)
        tree = ast.parse(updated)
        function = tree.body[0]
        assert isinstance(function, ast.FunctionDef) and function.name == "subtract", result
        expression = function.body[0].value
        assert isinstance(expression, ast.BinOp) and isinstance(expression.op, ast.Sub), result
        assert isinstance(expression.left, ast.Name) and expression.left.id == "left", result
        assert isinstance(expression.right, ast.Name) and expression.right.id == "right", result
        assert source.read_text(encoding="utf-8") == original
        assert list(root.iterdir()) == [source]
        print(f"PASS misleading path: proposal={result.path}, seconds={perf_counter() - start:.1f}; exact subtraction; source unchanged")


if __name__ == "__main__":
    main()

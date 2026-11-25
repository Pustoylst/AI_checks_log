import json

import pytest
from langchain_core.messages import AIMessage

from app.agent import FixProposalError, propose_fix
from app.config import Settings
from app.tools import build_repository_tools


class Model:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.seen = []

    def bind_tools(self, tools):
        return self

    def invoke(self, messages):
        self.seen.append(list(messages))
        return AIMessage(content=next(self.responses))


def proposal(path):
    return json.dumps(dict(path=path, explanation="Исправить вычитание",
                           old_text="return left + right", new_text="return left - right"))


def test_missing_path_retried_with_existing_file_context(tmp_path):
    source = tmp_path / "calculator.py"
    original = "def subtract(left, right):\n    return left + right\n"
    source.write_text(original, encoding="utf-8")
    model = Model([proposal("src/math_operations.py"), proposal("calculator.py")])
    result = propose_fix({}, tmp_path, Settings(_env_file=None), lambda *_: model)
    assert result.path == "calculator.py"
    assert "calculator.py" in model.seen[0][2].content
    assert "отсутствует" in model.seen[1][-1].content
    assert source.read_text(encoding="utf-8") == original
    assert not (tmp_path / "src").exists()


def test_repeated_missing_path_rejected_without_creating_file(tmp_path):
    model = Model([proposal("src/math_operations.py")] * 2)
    with pytest.raises(FixProposalError, match="отсутствует в репозитории"):
        propose_fix({}, tmp_path, Settings(_env_file=None), lambda *_: model)
    assert list(tmp_path.iterdir()) == []


def test_file_listing_excludes_environment_and_backups(tmp_path):
    (tmp_path / "calculator.py").write_text("source", encoding="utf-8")
    (tmp_path / "calculator.py.backup-123").write_text("backup", encoding="utf-8")
    (tmp_path / ".venv").mkdir()
    (tmp_path / ".venv" / "secret.py").write_text("env", encoding="utf-8")
    listing = next(t for t in build_repository_tools(tmp_path) if t.name == "list_repository_files")
    assert listing.invoke({}) == "calculator.py"

from langchain_core.messages import AIMessage
import pytest

from app.agent import analyze_log, propose_fix
from app.config import Settings


class Model:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.messages = []

    def bind_tools(self, tools):
        return self

    def invoke(self, messages):
        self.messages = list(messages)
        return AIMessage(content=next(self.responses))


def test_connected_repository_is_explicit_even_with_empty_repo_paths(tmp_path):
    model = Model(["Ответ"])
    analyze_log({"repo_paths": []}, tmp_path, Settings(_env_file=None), lambda *_: model)
    assert "Репозиторий подключён" in model.messages[0].content
    assert "repo_paths" in model.messages[0].content


def test_inexact_proposal_is_retried_with_actual_source(tmp_path):
    source = tmp_path / "a.py"
    source.write_text("return left + right\n", encoding="utf-8")
    model = Model([
        '{"path":"a.py","explanation":"Исправить вычисление","old_text":"return a + b","new_text":"return a - b"}',
        '{"path":"a.py","explanation":"Исправить вычисление","old_text":"return left + right","new_text":"return left - right"}',
    ])
    proposal = propose_fix({}, tmp_path, Settings(_env_file=None), lambda *_: model)
    assert proposal.old_text == "return left + right"
    assert "return left + right" in model.messages[-1].content
    assert source.read_text(encoding="utf-8") == "return left + right\n"


def test_repeated_inexact_proposal_is_rejected_without_writing(tmp_path):
    source = tmp_path / "a.py"
    source.write_text("original\n", encoding="utf-8")
    invalid = '{"path":"a.py","explanation":"Исправить вычисление","old_text":"invented","new_text":"replacement"}'
    model = Model([invalid, invalid, invalid])
    with pytest.raises(ValueError, match="точную безопасную замену: old_text не совпадает"):
        propose_fix({}, tmp_path, Settings(_env_file=None), lambda *_: model)
    assert source.read_text(encoding="utf-8") == "original\n"

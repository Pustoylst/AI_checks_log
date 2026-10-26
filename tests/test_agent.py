from pathlib import Path

from langchain_core.messages import AIMessage

from app.agent import _parse_fix_proposal, analyze_log, propose_fix
from app.config import Settings


class FakeModel:
    def __init__(self, responses: list[AIMessage]) -> None:
        self.responses = iter(responses)
        self.seen_messages = []

    def bind_tools(self, tools: list):
        return self

    def invoke(self, messages):
        self.seen_messages.append(messages)
        return next(self.responses)


def test_agent_calls_read_git_file_and_uses_result(tmp_path: Path) -> None:
    (tmp_path / "handler.py").write_text("raise RuntimeError('known failure')\n", encoding="utf-8")
    model = FakeModel(
        [
            AIMessage(
                content="",
                tool_calls=[
                    {"name": "read_git_file", "args": {"path": "handler.py"}, "id": "call-1", "type": "tool_call"}
                ],
            ),
            AIMessage(content="Причина подтверждена кодом handler.py: known failure."),
        ]
    )

    result = analyze_log(
        {"error": "known failure", "file": "handler.py"},
        repo_root=tmp_path,
        settings=Settings(_env_file=None, gigachat_credentials="test"),
        model_factory=lambda settings, model_name: model,
    )

    assert "handler.py" in result
    assert any("known failure" in str(message.content) for message in model.seen_messages[1])


def test_agent_uses_fallback_model_after_primary_failure() -> None:
    models = [
        RuntimeError("rate limit"),
        FakeModel([AIMessage(content="fallback response")]),
    ]

    def model_factory(settings, model_name):
        current = models.pop(0)
        if isinstance(current, Exception):
            raise current
        return current

    result = analyze_log(
        {"error": "timeout"},
        settings=Settings(_env_file=None, gigachat_credentials="test"),
        model_factory=model_factory,
    )

    assert result == "fallback response"


def test_agent_proposes_exact_fix_after_reading_file(tmp_path: Path) -> None:
    (tmp_path / "service.py").write_text("TIMEOUT = 60\n", encoding="utf-8")
    model = FakeModel(
        [
            AIMessage(
                content="",
                tool_calls=[
                    {"name": "read_git_file", "args": {"path": "service.py"}, "id": "call-fix", "type": "tool_call"}
                ],
            ),
            AIMessage(
                content='{"path":"service.py","explanation":"Увеличить таймаут","old_text":"TIMEOUT = 60","new_text":"TIMEOUT = 120"}'
            ),
        ]
    )

    proposal = propose_fix(
        {"message": "request timeout", "file": "service.py"},
        repo_root=tmp_path,
        settings=Settings(_env_file=None, gigachat_credentials="test"),
        model_factory=lambda settings, model_name: model,
    )

    assert proposal.path == "service.py"
    assert proposal.old_text == "TIMEOUT = 60"
    assert proposal.new_text == "TIMEOUT = 120"
    assert any("TIMEOUT = 60" in str(message.content) for message in model.seen_messages[1])


def test_parse_fix_proposal_accepts_markdown_json() -> None:
    proposal = _parse_fix_proposal(
        "Вот предложение:\n```json\n"
        '{"path":"calculator.py","explanation":"Исправить операцию","old_text":"left + right",'
        '"new_text":"left - right"}\n```'
    )

    assert proposal.path == "calculator.py"
    assert proposal.new_text == "left - right"


def test_agent_normalizes_report_into_fix_proposal(tmp_path: Path) -> None:
    (tmp_path / "calculator.py").write_text("return left + right\n", encoding="utf-8")
    model = FakeModel(
        [
            AIMessage(content="Проблема в операции сложения вместо вычитания."),
            AIMessage(
                content='{"path":"calculator.py","explanation":"Исправить операцию","old_text":"return left + right","new_text":"return left - right"}'
            ),
        ]
    )

    proposal = propose_fix(
        {"message": "tests failed", "file": "calculator.py"},
        repo_root=tmp_path,
        settings=Settings(_env_file=None, gigachat_credentials="test"),
        model_factory=lambda settings, model_name: model,
    )

    assert proposal.new_text == "return left - right"
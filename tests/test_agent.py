from pathlib import Path

from langchain_core.messages import AIMessage

from app.agent import analyze_log
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
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
        self.seen_messages.append(list(messages))
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
        settings=Settings(_env_file=None),
        model_factory=lambda settings, model_name: model,
    )

    assert "handler.py" in result
    assert any("known failure" in str(message.content) for message in model.seen_messages[1])


def test_agent_marks_preprocessed_report_as_excerpt() -> None:
    model = FakeModel([AIMessage(content="Готовая выжимка проанализирована.")])

    analyze_log(
        {"log_format": "preprocessed", "report": "## Ошибки\n\nRabbitMQ is not available"},
        settings=Settings(_env_file=None),
        model_factory=lambda settings, model_name: model,
    )

    first_message = str(model.seen_messages[0][1].content)
    system_message = str(model.seen_messages[0][0].content)
    assert "автоматическая выжимка" in first_message
    assert "не полный файл" in first_message
    assert "только на русском языке" in system_message


def test_agent_extracts_trace_chain_from_uploaded_jsonl_text() -> None:
    model = FakeModel([AIMessage(content="Причина найдена.")])
    rows = [
        '{"tr":"trace-A","l":"Info","lg":"WebServer","mt":"request received"}',
        '{"tr":"trace-B","l":"Info","lg":"Worker","mt":"unrelated trace"}',
    ]
    rows.extend(
        f'{{"tr":"trace-A","l":"Info","lg":"Service","mt":"step {index}"}}'
        for index in range(15)
    )
    rows.extend(
        [
            '{"tr":"trace-A","l":"Error","lg":"IntegrationService","mt":"broker unavailable"}',
            '{"tr":"trace-A","l":"Info","lg":"WebServer","mt":"request failed"}',
        ]
    )

    analyze_log(
        {"log_format": "text", "message": "\n".join(rows)},
        settings=Settings(_env_file=None),
        model_factory=lambda settings, model_name: model,
    )

    first_message = str(model.seen_messages[0][1].content)
    assert "Цепочки событий с одинаковым trace ID" in first_message
    assert "request received" in first_message
    assert "broker unavailable" in first_message
    assert "request failed" in first_message
    assert "Цепочка сокращена" in first_message
    trace_context = first_message.split(
        "Цепочки событий с одинаковым trace ID", 1
    )[1]
    assert "unrelated trace" not in trace_context


def test_local_failure_does_not_retry_cloud() -> None:
    import pytest
    calls = []

    def model_factory(settings, model_name):
        calls.append(model_name)
        raise ConnectionError("Ollama unavailable")

    with pytest.raises(ConnectionError, match="Ollama unavailable"):
        analyze_log({"error": "timeout"}, settings=Settings(_env_file=None), model_factory=model_factory)
    assert calls == ["qwen3:8b"]


def test_agent_rewrites_english_analysis_as_russian() -> None:
    model = FakeModel(
        [
            AIMessage(content="The test failed because the expected value was incorrect."),
            AIMessage(content="Тест завершился ошибкой из-за неверного ожидаемого значения."),
        ]
    )

    answer = analyze_log(
        {"message": "assertion failed"},
        settings=Settings(_env_file=None),
        model_factory=lambda *_: model,
    )

    assert answer.startswith("Тест завершился ошибкой из-за неверного ожидаемого значения.")
    assert "по-русски" in str(model.seen_messages[1][0].content)
    assert model.seen_messages[1][1].content == "The test failed because the expected value was incorrect."


def test_agent_rewrites_english_ci_analysis_as_russian() -> None:
    model = FakeModel(
        [
            AIMessage(content="The CI job failed because the test expected 1 but got 9."),
            AIMessage(content="CI-задание упало: тест ожидал 1, но получил 9."),
        ]
    )

    answer = analyze_log(
        {"run_id": 42, "ci_logs": "FAILED test_calculator.py::test_subtracts_numbers"},
        settings=Settings(_env_file=None),
        model_factory=lambda *_: model,
    )

    assert answer.startswith("CI-задание упало")
    assert "по-русски" in str(model.seen_messages[1][0].content)
    assert model.seen_messages[1][1].content == "The CI job failed because the test expected 1 but got 9."


def test_agent_retries_translation_if_first_prompt_is_ignored() -> None:
    model = FakeModel(
        [
            AIMessage(content="The test failed because the expected value was incorrect."),
            AIMessage(content="The test failed because the expected value was incorrect."),
            AIMessage(content="Тест завершился ошибкой из-за неверного ожидаемого значения."),
        ]
    )

    answer = analyze_log(
        {"message": "assertion failed"},
        settings=Settings(_env_file=None),
        model_factory=lambda *_: model,
    )

    assert answer.startswith("Тест завершился ошибкой из-за неверного ожидаемого значения.")
    assert len(model.seen_messages) == 3
    assert "Не повторяй английский" in str(model.seen_messages[2][0].content)


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
        settings=Settings(_env_file=None),
        model_factory=lambda settings, model_name: model,
    )

    assert proposal.path == "service.py"
    assert proposal.old_text == "TIMEOUT = 60"
    assert proposal.new_text == "TIMEOUT = 120"
    assert any("TIMEOUT = 60" in str(message.content) for message in model.seen_messages[1])


def test_agent_retries_fix_with_russian_explanation(tmp_path: Path) -> None:
    (tmp_path / "service.py").write_text("TIMEOUT = 60\n", encoding="utf-8")
    model = FakeModel(
        [
            AIMessage(
                content='{"path":"service.py","explanation":"Increase the timeout",'
                '"old_text":"TIMEOUT = 60","new_text":"TIMEOUT = 120"}'
            ),
            AIMessage(
                content='{"path":"service.py","explanation":"Увеличить таймаут",'
                '"old_text":"TIMEOUT = 60","new_text":"TIMEOUT = 120"}'
            ),
        ]
    )

    proposal = propose_fix(
        {"message": "request timeout", "file": "service.py"},
        repo_root=tmp_path,
        settings=Settings(_env_file=None),
        model_factory=lambda settings, model_name: model,
    )

    assert proposal.explanation == "Увеличить таймаут"
    assert "обязательно сформулируй на русском языке" in str(model.seen_messages[1][-1].content)


def test_ci_fix_rejects_test_file_and_retries_with_source(tmp_path: Path) -> None:
    (tmp_path / "calculator.py").write_text("return left + right\n", encoding="utf-8")
    (tmp_path / "test_calculator.py").write_text("assert subtract(5, 4) == 1\n", encoding="utf-8")
    model = FakeModel(
        [
            AIMessage(
                content='{"path":"test_calculator.py","explanation":"Изменить ожидание теста",'
                '"old_text":"assert subtract(5, 4) == 1","new_text":"assert subtract(5, 4) == 9"}'
            ),
            AIMessage(
                content='{"path":"calculator.py","explanation":"Исправить операцию",'
                '"old_text":"return left + right","new_text":"return left - right"}'
            ),
        ]
    )

    proposal = propose_fix(
        {"run_id": 42, "ci_logs": "FAILED test_calculator.py::test_subtracts_numbers"},
        repo_root=tmp_path,
        settings=Settings(_env_file=None),
        model_factory=lambda settings, model_name: model,
    )

    assert proposal.path == "calculator.py"
    assert proposal.new_text == "return left - right"
    assert len(model.seen_messages) == 2
    correction = str(model.seen_messages[1][-1].content)
    assert "Запрещено менять тесты" in correction
    assert "не тесты" in correction


def test_ci_fix_rejects_workflow_config(tmp_path: Path) -> None:
    workflow = tmp_path / ".github" / "workflows" / "ci.yml"
    workflow.parent.mkdir(parents=True)
    workflow.write_text("run: python -m pytest -q\n", encoding="utf-8")
    (tmp_path / "calculator.py").write_text("return left + right\n", encoding="utf-8")
    model = FakeModel(
        [
            AIMessage(
                content='{"path":".github/workflows/ci.yml","explanation":"Добавить проверку стиля",'
                '"old_text":"run: python -m pytest -q","new_text":"run: python -m flake8"}'
            ),
            AIMessage(
                content='{"path":"calculator.py","explanation":"Исправить операцию",'
                '"old_text":"return left + right","new_text":"return left - right"}'
            ),
        ]
    )

    proposal = propose_fix(
        {"run_id": 42, "ci_logs": "FAILED test_calculator.py::test_subtracts_numbers"},
        repo_root=tmp_path,
        settings=Settings(_env_file=None),
        model_factory=lambda settings, model_name: model,
    )

    assert proposal.path == "calculator.py"
    assert "конфигурацию CI/CD" in str(model.seen_messages[1][-1].content)


def test_ci_fix_uses_previous_analysis(tmp_path: Path) -> None:
    (tmp_path / "calculator.py").write_text("return left + right\n", encoding="utf-8")
    model = FakeModel(
        [
            AIMessage(
                content='{"path":"calculator.py","explanation":"Исправить операцию",'
                '"old_text":"return left + right","new_text":"return left - right"}'
            )
        ]
    )

    propose_fix(
        {"run_id": 42, "ci_logs": "FAILED test_calculator.py::test_subtracts_numbers"},
        repo_root=tmp_path,
        settings=Settings(_env_file=None),
        model_factory=lambda settings, model_name: model,
        analysis="Функция subtract в calculator.py складывает аргументы вместо вычитания.",
    )

    assert any(
        "Функция subtract в calculator.py" in str(message.content)
        for message in model.seen_messages[0]
    )
    system_text = str(model.seen_messages[0][0].content)
    assert "Не меняй тесты" in system_text or "Никогда не меняй тесты" in system_text


def test_parse_fix_proposal_accepts_markdown_json() -> None:
    proposal = _parse_fix_proposal(
        "Вот предложение:\n```json\n"
        '{"path":"calculator.py","explanation":"Исправить операцию","old_text":"left + right",'
        '"new_text":"left - right"}\n```'
    )

    assert proposal.path == "calculator.py"
    assert proposal.new_text == "left - right"


def test_parse_fix_proposal_extracts_json_surrounded_by_explanation() -> None:
    proposal = _parse_fix_proposal(
        'Here is the proposal:\n{"path":"calculator.py","explanation":"Исправить операцию",'
        '"old_text":"left + right","new_text":"left - right"}\nDone.'
    )

    assert proposal.path == "calculator.py"
    assert proposal.explanation == "Исправить операцию"


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
        settings=Settings(_env_file=None),
        model_factory=lambda settings, model_name: model,
    )

    assert proposal.new_text == "return left - right"

def test_agent_marks_overview_as_aggregate_and_uses_only_report() -> None:
    model = FakeModel([AIMessage(content="Главная проблема — RabbitMQ.")])

    analyze_log(
        {
            "log_format": "overview",
            "report": "# Общая сводка\n\nRabbitMQ is not available",
            "stats": {"files_scanned": 600},
        },
        settings=Settings(_env_file=None),
        model_factory=lambda settings, model_name: model,
    )

    first_message = str(model.seen_messages[0][1].content)
    assert "общая сводка по многим файлам" in first_message
    assert "какие конкретные файлы" in first_message
    assert "RabbitMQ is not available" in first_message
    assert "files_scanned" not in first_message


def test_agent_includes_follow_up_question() -> None:
    model = FakeModel([AIMessage(content="Ответ по вопросу.")])

    analyze_log(
        {
            "log_format": "preprocessed",
            "report": "## Ошибки\n\nRabbitMQ is not available",
            "question": "Почему RabbitMQ недоступен?",
        },
        settings=Settings(_env_file=None),
        model_factory=lambda settings, model_name: model,
    )

    first_message = str(model.seen_messages[0][1].content)
    assert "Почему RabbitMQ недоступен?" in first_message

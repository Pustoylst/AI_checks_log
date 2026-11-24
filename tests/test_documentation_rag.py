import os
from pathlib import Path

from langchain_core.messages import AIMessage

from app.agent import analyze_log
from app.config import Settings
from app.documentation_rag import build_documentation_tool


def test_documentation_search_returns_relevant_html_excerpt(tmp_path: Path) -> None:
    docs = tmp_path / "rx262"
    docs.mkdir()
    (docs / "integration.htm").write_text(
        """<html>
        <head><title>Directum RX / Интеграция</title>
        <meta name="description" content="Проблемы подключения" /></head>
        <body><div id="idheader">Не индексировать шапку</div>
        <div id="idcontent"><h1>Сервис интеграции</h1>
        <p>Если возникает BrokerNotAvailableException, проверьте доступность RabbitMQ.</p>
        <script>ignore_this_secret()</script></div></body></html>""",
        encoding="utf-8",
    )

    result = build_documentation_tool(docs).invoke(
        {"query": "BrokerNotAvailableException RabbitMQ"}
    )

    assert "rx262/integration.htm" in result
    assert "Directum RX / Интеграция" in result
    assert "проверьте доступность RabbitMQ" in result
    assert "ignore_this_secret" not in result
    assert "Не индексировать шапку" not in result


def test_documentation_search_refreshes_changed_pages(tmp_path: Path) -> None:
    docs = tmp_path / "rx262"
    docs.mkdir()
    page = docs / "refresh.htm"
    page.write_text(
        "<html><head><title>RefreshToken</title></head>"
        "<body><div id='idcontent'><p>FirstRevision detail token.</p></div></body></html>",
        encoding="utf-8",
    )
    search = build_documentation_tool(docs)
    first = search.invoke({"query": "RefreshToken"})
    assert "FirstRevision detail" in first

    page.write_text(
        "<html><head><title>RefreshToken</title></head>"
        "<body><div id='idcontent'><p>SecondRevision detail token.</p></div></body></html>",
        encoding="utf-8",
    )
    stat = page.stat()
    os.utime(page, ns=(stat.st_atime_ns, stat.st_mtime_ns + 2_000_000_000))

    second = search.invoke({"query": "RefreshToken"})
    assert "SecondRevision detail" in second
    assert "FirstRevision detail" not in second


class _Model:
    def __init__(self) -> None:
        self.responses = iter(
            [
                AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "name": "search_directum_documentation",
                            "args": {"query": "BrokerNotAvailableException RabbitMQ"},
                            "id": "docs-1",
                            "type": "tool_call",
                        }
                    ],
                ),
                AIMessage(content="Справка подтверждает проверку доступности RabbitMQ."),
            ]
        )
        self.seen_messages = []

    def bind_tools(self, tools: list):
        assert any(tool.name == "search_directum_documentation" for tool in tools)
        return self

    def invoke(self, messages):
        self.seen_messages.append(list(messages))
        return next(self.responses)


def test_agent_uses_documentation_tool_when_model_selects_it(tmp_path: Path) -> None:
    docs = tmp_path / "rx262"
    docs.mkdir()
    (docs / "rabbitmq.htm").write_text(
        "<html><head><title>RabbitMQ в Directum RX</title></head>"
        "<body><div id='idcontent'><p>Проверьте доступность RabbitMQ.</p></div></body></html>",
        encoding="utf-8",
    )
    model = _Model()
    settings = Settings(_env_file=None, directum_docs_path=docs)

    answer = analyze_log(
        {"message": "BrokerNotAvailableException"},
        settings=settings,
        model_factory=lambda *_: model,
    )

    assert "RabbitMQ" in answer
    retrieved = str(model.seen_messages[1][-1].content)
    assert "rx262/rabbitmq.htm" in retrieved
    assert "Проверьте доступность RabbitMQ" in retrieved

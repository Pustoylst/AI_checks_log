import json

import httpx
import pytest
from langchain_core.messages import AIMessage

from app import agent, documentation_rag as rag, documentation_vectors as vectors
from app.config import Settings


@pytest.mark.parametrize("endpoint", ["tags", "embed"])
def test_null_ollama_response(endpoint):
    with httpx.Client(base_url="http://127.0.0.1:11434", transport=httpx.MockTransport(
        lambda _: httpx.Response(200, content="null"))) as client:
        with pytest.raises(vectors.VectorSearchError):
            if endpoint == "tags":
                vectors.model_identity(client, Settings(_env_file=None))
            else:
                vectors.embed(client, Settings(_env_file=None), ["text"])


def test_reject_model_change_before_batch_commit(tmp_path, monkeypatch):
    conn = rag._connect(tmp_path / "index.sqlite3")
    conn.execute("INSERT INTO chunks VALUES ('a.htm', 'A', 'text')")
    conn.commit()
    identities = iter(["old", "old", "new"])
    monkeypatch.setattr(vectors, "model_identity", lambda *args: next(identities))
    monkeypatch.setattr(vectors, "client_for", lambda _: httpx.Client(base_url="http://127.0.0.1:11434", transport=httpx.MockTransport(
        lambda _: httpx.Response(200, json={"embeddings": [[1., 0.]]}))))
    with pytest.raises(vectors.VectorSearchError, match="порция не сохранена"):
        vectors.build_vectors(conn, Settings(_env_file=None))
    assert conn.execute("SELECT COUNT(*) FROM vectors").fetchone()[0] == 0
    conn.close()


def test_tool_sources_and_correct_second_link_are_preserved(tmp_path, monkeypatch):
    docs = tmp_path / "docs"
    docs.mkdir()
    first = (("a.htm", "A", "initial"),)
    second = (("b.htm", "B", "better match"),)
    def search(root, query, **kwargs):
        return second if query == "refine" else first
    monkeypatch.setattr(agent, "search_documentation", search)
    monkeypatch.setattr(rag, "search_documentation", search)
    class Model:
        responses = iter([
            AIMessage(content="", tool_calls=[{"name": "search_directum_documentation", "args": {"query": "refine"}, "id": "1"}]),
            AIMessage(content="Смотрите справку: [Раздел B](rx262/b.htm)"),
        ])
        def bind_tools(self, tools):
            return self
        def invoke(self, messages):
            return next(self.responses)
    answer = agent.analyze_log({"message": "Directum error"},
        settings=Settings(_env_file=None, directum_docs_path=docs), model_factory=lambda *_: Model())
    assert "[Раздел B](rx262/b.htm)" in answer
    assert "`b.htm`" in answer
    assert "`a.htm`" in answer


def test_explicit_refresh_detects_preserved_metadata(tmp_path):
    import os
    page = tmp_path / "a.htm"
    page.write_text("<body><p>old content</p></body>", encoding="utf-8")
    conn = rag._connect(tmp_path / "index.sqlite3")
    with conn:
        rag._refresh_index(tmp_path, conn)
    stat = page.stat()
    page.write_text("<body><p>new content</p></body>", encoding="utf-8")
    os.utime(page, ns=(stat.st_atime_ns, stat.st_mtime_ns))
    with conn:
        rag._refresh_index(tmp_path, conn, force=True)
    assert conn.execute("SELECT content FROM chunks").fetchone()[0] == "new content"
    conn.close()

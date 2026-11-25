import json
import sqlite3

import httpx
import numpy as np
import pytest

from app.config import Settings
from app import documentation_vectors as vectors
from app import documentation_rag as rag


def fake_client(calls, digest="revision1", bad=None):
    def handler(request):
        if request.url.path == "/api/tags":
            return httpx.Response(200, json={"models": [{"name": "bge-m3:latest", "digest": digest}]})
        body = json.loads(request.content)
        assert request.url.path == "/api/embed"
        assert body["truncate"] is False
        calls.extend(body["input"])
        payload = {"embeddings": bad if bad is not None else [[1., 0.] for _ in body["input"]]}
        return httpx.Response(200, content=json.dumps(payload), headers={"content-type": "application/json"})
    return httpx.Client(base_url="http://127.0.0.1:11434", transport=httpx.MockTransport(handler))


def setup_docs(tmp_path, monkeypatch):
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "broker.htm").write_text("<html><body><p>RabbitMQ configuration</p></body></html>", encoding="utf-8")
    cache = tmp_path / "index.sqlite3"
    monkeypatch.setattr(rag, "_cache_path", lambda _: cache)
    settings = Settings(_env_file=None, directum_docs_path=docs)
    conn = rag._connect(cache)
    with conn:
        rag._refresh_index(docs, conn)
    return docs, settings, conn


def test_semantic_without_word_overlap_and_resume(tmp_path, monkeypatch):
    docs, settings, conn = setup_docs(tmp_path, monkeypatch)
    calls = []
    monkeypatch.setattr(vectors, "client_for", lambda _: fake_client(calls))
    first = vectors.build_vectors(conn, settings, progress=lambda *a, **k: None)
    assert first["embedded"] == 1
    assert vectors.build_vectors(conn, settings)["embedded"] == 0
    assert len(calls) == 1
    status = []
    result = rag.search_documentation(docs, "нет связи с брокером", settings=settings, status=status)
    assert result[0][0] == "broker.htm"
    assert not status
    conn.close()


def test_changed_deleted_docs_and_model_revision(tmp_path, monkeypatch):
    docs, settings, conn = setup_docs(tmp_path, monkeypatch)
    calls = []
    monkeypatch.setattr(vectors, "client_for", lambda _: fake_client(calls))
    vectors.build_vectors(conn, settings, progress=lambda *a, **k: None)
    page = docs / "broker.htm"
    page.write_text("<html><body><p>NEW RabbitMQ configuration changed</p></body></html>", encoding="utf-8")
    status = []
    result = rag.search_documentation(docs, "RabbitMQ", settings=settings, status=status)
    assert status and "NEW" in result[0][2]
    assert vectors.build_vectors(conn, settings, progress=lambda *a, **k: None)["embedded"] == 1
    monkeypatch.setattr(vectors, "client_for", lambda _: fake_client(calls, digest="revision2"))
    with pytest.raises(vectors.VectorSearchError, match="устарел"):
        vectors.vector_search(conn, "RabbitMQ", settings)
    page.unlink()
    assert not rag.search_documentation(docs, "RabbitMQ", settings=settings)
    conn.close()


def test_ollama_unavailable_falls_back(tmp_path, monkeypatch):
    docs, settings, conn = setup_docs(tmp_path, monkeypatch)
    def unavailable(*args):
        raise httpx.ConnectError("offline")
    monkeypatch.setattr(vectors, "client_for", unavailable)
    status = []
    assert rag.search_documentation(docs, "RabbitMQ", settings=settings, status=status)
    assert "BM25" in status[0]
    conn.close()


@pytest.mark.parametrize("bad", [[], [[0., 0.]], [[float('nan'), 1.]], [[1.], [2.]]])
def test_reject_invalid_embedding(bad):
    settings = Settings(_env_file=None)
    with fake_client([], bad=bad) as client:
        with pytest.raises(vectors.VectorSearchError):
            vectors.embed(client, settings, ["text"])


def test_fusion_and_cosine_threshold(tmp_path, monkeypatch):
    a = (1, "a.htm", "A", "one")
    b = (2, "b.htm", "B", "two")
    assert vectors.fuse_results([a, b], [b])[0][0] == "b.htm"
    docs, settings, conn = setup_docs(tmp_path, monkeypatch)
    monkeypatch.setattr(vectors, "client_for", lambda _: fake_client([]))
    vectors.build_vectors(conn, settings, progress=lambda *a, **k: None)
    monkeypatch.setattr(vectors, "embed", lambda *args: np.asarray([[0., 1.]], dtype="<f4"))
    assert vectors.vector_search(conn, "unrelated", settings) == []
    conn.close()

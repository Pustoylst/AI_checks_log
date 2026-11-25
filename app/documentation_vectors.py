"""Local Ollama embeddings and resumable SQLite vector storage."""
import hashlib
import sqlite3

import httpx
import numpy as np

from app.config import Settings


class VectorSearchError(RuntimeError):
    """Vector retrieval is unavailable; lexical search can still be used."""


def content_key(title: str, content: str) -> str:
    return hashlib.sha256(f"{title}\n{content}".encode("utf-8")).hexdigest()


def model_identity(client: httpx.Client, settings: Settings) -> str:
    response = client.get("/api/tags")
    response.raise_for_status()
    requested = settings.rag_embedding_model
    payload = response.json()
    if not isinstance(payload, dict) or not isinstance(payload.get("models"), list):
        raise VectorSearchError("Ollama вернула некорректный список моделей")
    for model in payload["models"]:
        if isinstance(model, dict) and model.get("name") in {requested, requested + ":latest"}:
            if isinstance(model.get("digest"), str) and model["digest"]:
                return model["digest"]
    raise VectorSearchError(f"Модель {requested} не найдена в Ollama")


def embed(client: httpx.Client, settings: Settings, texts: list[str]) -> np.ndarray:
    response = client.post("/api/embed", json={
        "model": settings.rag_embedding_model, "input": texts,
        "truncate": False, "keep_alive": "5m",
    })
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict) or not isinstance(payload.get("embeddings"), list):
        raise VectorSearchError("Ollama вернула некорректный ответ эмбеддингов")
    try:
        matrix = np.asarray(payload["embeddings"], dtype="<f4")
    except (TypeError, ValueError) as error:
        raise VectorSearchError("Некорректный формат векторов Ollama") from error
    if matrix.ndim != 2 or matrix.shape[0] != len(texts) or not matrix.shape[1]:
        raise VectorSearchError("Ollama вернула неверное число или размер векторов")
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    if not np.isfinite(matrix).all() or not np.isfinite(norms).all() or (norms <= 0).any():
        raise VectorSearchError("Ollama вернула некорректные векторы")
    return matrix / norms


def connect_vectors(connection: sqlite3.Connection) -> None:
    connection.execute(
        "CREATE TABLE IF NOT EXISTS vectors (model TEXT NOT NULL, key TEXT NOT NULL, "
        "vector BLOB NOT NULL, PRIMARY KEY (model, key))"
    )


def client_for(settings: Settings) -> httpx.Client:
    return httpx.Client(base_url=settings.ollama_base_url, trust_env=False,
                        timeout=settings.ollama_timeout_seconds)


def build_vectors(connection: sqlite3.Connection, settings: Settings, progress=print) -> dict:
    """Commit each batch, so interruption never discards completed embeddings."""
    connect_vectors(connection)
    connection.commit()
    rows = connection.execute("SELECT title, content FROM chunks").fetchall()
    with client_for(settings) as client:
        identity = model_identity(client, settings)
        existing = {row[0] for row in connection.execute(
            "SELECT key FROM vectors WHERE model = ?", (identity,))}
        pending = {content_key(title, text): f"{title}\n{text}"
                   for title, text in rows if content_key(title, text) not in existing}
        items = list(pending.items())
        for start in range(0, len(items), settings.rag_embedding_batch_size):
            batch = items[start:start + settings.rag_embedding_batch_size]
            if model_identity(client, settings) != identity:
                raise VectorSearchError("Модель изменилась во время индексации; повторите команду")
            matrix = embed(client, settings, [text for _, text in batch])
            if model_identity(client, settings) != identity:
                raise VectorSearchError("Модель изменилась во время индексации; порция не сохранена")
            with connection:
                connection.executemany("INSERT OR REPLACE INTO vectors VALUES (?, ?, ?)",
                    [(identity, key, vector.astype("<f4").tobytes())
                     for (key, _), vector in zip(batch, matrix)])
            progress(f"Векторы: {min(start + len(batch), len(items))}/{len(items)}", flush=True)
    return {"chunks": len(rows), "embedded": len(items), "model_digest": identity}


def vector_search(connection: sqlite3.Connection, query: str, settings: Settings):
    connect_vectors(connection)
    rows = connection.execute("SELECT rowid, path, title, content FROM chunks").fetchall()
    if not rows:
        return []
    with client_for(settings) as client:
        identity = model_identity(client, settings)
        stored = dict(connection.execute("SELECT key, vector FROM vectors WHERE model = ?", (identity,)))
        keys = [content_key(title, content) for _, _, title, content in rows]
        # Never silently use a partial index or embeddings from another model revision.
        if any(key not in stored for key in keys):
            raise VectorSearchError("Векторный индекс не готов или устарел. Выполните python -m tools.index_documentation")
        query_vector = embed(client, settings, [query])[0]
        if model_identity(client, settings) != identity:
            raise VectorSearchError("Модель изменилась во время поиска; повторите запрос")
    matrix = np.stack([np.frombuffer(stored[key], dtype="<f4") for key in keys])
    if matrix.shape[1] != query_vector.shape[0]:
        raise VectorSearchError("Размерность индекса изменилась; перестройте векторный индекс")
    scores = matrix @ query_vector
    order = np.argsort(-scores, kind="stable")[:20]
    return [rows[int(i)] for i in order if scores[i] >= settings.rag_vector_min_similarity]


def fuse_results(lexical, semantic, limit=5):
    """Reciprocal rank fusion, retaining source chunks rather than invented links."""
    scores, rows = {}, {}
    for ranked in (lexical, semantic):
        for rank, row in enumerate(ranked, 1):
            key = row[0]
            rows[key] = row[1:]
            scores[key] = scores.get(key, 0.0) + 1 / (60 + rank)
    ordered = sorted(scores, key=lambda key: -scores[key])
    return tuple(rows[key] for key in ordered[:limit])

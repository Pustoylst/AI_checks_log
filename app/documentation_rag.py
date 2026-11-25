"""Local hybrid BM25 and BGE-M3 retrieval over Directum RX HTML documentation."""

from html.parser import HTMLParser
import hashlib
import os
from pathlib import Path
import re
import sqlite3
import tempfile
from threading import RLock
import logging

import httpx
from app.config import Settings, get_settings
from app.documentation_vectors import VectorSearchError, vector_search, fuse_results

from langchain_core.tools import tool

_BLOCK_TAGS = {"br", "h1", "h2", "h3", "h4", "h5", "h6", "li", "p", "pre", "td", "th", "tr"}
_SKIP_TAGS = {"script", "style", "noscript", "svg"}
_STOP_WORDS = {
    "для", "или", "как", "что", "это", "при", "если", "где", "когда",
    "the", "and", "for", "with", "from", "this", "that",
}
_WORD_RE = re.compile(r"[^\W_]+", re.UNICODE)
_INDEX_LOCK = RLock()
_CHUNK_CHARS = 1200
_CHUNK_OVERLAP = 160
_RESULT_COUNT = 5


class DocumentationSearchError(RuntimeError):
    """The documentation index could not be searched."""


class _DocumentationHTMLParser(HTMLParser):
    """Extract page metadata and visible text from Help & Manual HTML."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title_parts: list[str] = []
        self.description = ""
        self.blocks: list[str] = []
        self._block_parts: list[str] = []
        self._in_title = False
        self._in_body = False
        self._content_found = False
        self._content_depth = 0
        self._skip_stack: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if tag == "title":
            self._in_title = True
        if tag == "meta" and (attributes.get("name") or "").casefold() == "description":
            self.description = attributes.get("content") or ""
        if tag == "body":
            self._in_body = True

        if self._skip_stack:
            if tag not in {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}:
                self._skip_stack.append(tag)
            return

        if tag in _SKIP_TAGS or attributes.get("id") in {"idheader", "idnav", "printheader"}:
            if tag not in {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}:
                self._skip_stack.append(tag)
            return

        if tag == "div" and attributes.get("id") == "idcontent":
            self._content_found = True
            self._content_depth = 1
        elif self._content_depth and tag == "div":
            self._content_depth += 1

        if self._should_capture() and tag in _BLOCK_TAGS:
            self._flush_block()

    def handle_endtag(self, tag: str) -> None:
        if self._skip_stack:
            if tag == self._skip_stack[-1]:
                self._skip_stack.pop()
            return

        if tag == "title":
            self._in_title = False
        if self._should_capture() and tag in _BLOCK_TAGS:
            self._flush_block()
        if tag == "div" and self._content_depth:
            self._content_depth -= 1
        if tag == "body":
            self._in_body = False

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self.title_parts.append(data)
        if self._should_capture():
            text = " ".join(data.split())
            if text:
                self._block_parts.append(text)

    def _should_capture(self) -> bool:
        return self._in_body and (
            self._content_depth > 0 or not self._content_found
        ) and not self._skip_stack

    def _flush_block(self) -> None:
        text = " ".join(self._block_parts).strip()
        if text:
            self.blocks.append(text)
        self._block_parts.clear()


def _chunks(blocks: list[str]) -> list[str]:
    result: list[str] = []
    current = ""
    for block in blocks:
        remaining = block
        while len(remaining) > _CHUNK_CHARS:
            if current:
                result.append(current)
                current = ""
            cut = remaining.rfind(" ", 0, _CHUNK_CHARS)
            cut = cut if cut > _CHUNK_CHARS // 2 else _CHUNK_CHARS
            result.append(remaining[:cut].strip())
            remaining = remaining[max(0, cut - _CHUNK_OVERLAP):]
        if not remaining:
            continue
        if current and len(current) + len(remaining) + 1 > _CHUNK_CHARS:
            result.append(current)
            current = ""
        current = f"{current} {remaining}".strip()
    if current:
        result.append(current)
    return result


def _cache_path(root: Path) -> Path:
    local_app_data = os.environ.get("LOCALAPPDATA")
    cache_root = Path(local_app_data) / "AI_checks_log" / "rag" if local_app_data else (
        Path(tempfile.gettempdir()) / "AI_checks_log" / "rag"
    )
    digest = hashlib.sha256(str(root).encode("utf-8")).hexdigest()[:16]
    return cache_root / f"directum-rx-{digest}.sqlite3"


def _read_document(path: Path) -> tuple[str, str, list[str]]:
    parser = _DocumentationHTMLParser()
    parser.feed(path.read_text(encoding="utf-8-sig", errors="replace"))
    parser.close()
    parser._flush_block()
    title = " ".join(" ".join(parser.title_parts).split()) or path.stem
    title = re.sub(r"\s*[>|»]\s*", " / ", title)
    metadata = " ".join(parser.description.split())
    return title, metadata, _chunks(parser.blocks)


def _connect(index_path: Path) -> sqlite3.Connection:
    index_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(index_path, timeout=60)
    connection.execute(
        "CREATE TABLE IF NOT EXISTS documents "
        "(path TEXT PRIMARY KEY, size INTEGER NOT NULL, modified_ns INTEGER NOT NULL)"
    )
    connection.execute(
        "CREATE VIRTUAL TABLE IF NOT EXISTS chunks USING "
        "fts5(path UNINDEXED, title, content, tokenize='unicode61')"
    )
    return connection


def _refresh_index(root: Path, connection: sqlite3.Connection, *, force: bool = False) -> None:
    files = sorted(
        (path for path in root.rglob("*") if path.is_file() and path.suffix.casefold() in {".htm", ".html"}),
        key=lambda path: path.as_posix().casefold(),
    )
    current: dict[str, tuple[Path, int, int]] = {}
    for path in files:
        resolved = path.resolve()
        if resolved != root and root not in resolved.parents:
            continue
        stat = resolved.stat()
        relative = resolved.relative_to(root).as_posix()
        current[relative] = (resolved, stat.st_size, stat.st_mtime_ns)

    indexed = {
        path: (size, modified_ns)
        for path, size, modified_ns in connection.execute(
            "SELECT path, size, modified_ns FROM documents"
        )
    }

    for relative in indexed.keys() - current.keys():
        connection.execute("DELETE FROM chunks WHERE path = ?", (relative,))
        connection.execute("DELETE FROM documents WHERE path = ?", (relative,))

    for relative, (path, size, modified_ns) in current.items():
        if not force and indexed.get(relative) == (size, modified_ns):
            continue
        title, description, chunks = _read_document(path)
        connection.execute("DELETE FROM chunks WHERE path = ?", (relative,))
        searchable_title = f"{title} {description}".strip()
        connection.executemany(
            "INSERT INTO chunks (path, title, content) VALUES (?, ?, ?)",
            [(relative, searchable_title, chunk) for chunk in chunks],
        )
        connection.execute(
            "INSERT INTO documents (path, size, modified_ns) VALUES (?, ?, ?) "
            "ON CONFLICT(path) DO UPDATE SET size=excluded.size, modified_ns=excluded.modified_ns",
            (relative, size, modified_ns),
        )


def _search_index(root_text: str, query: str, settings: Settings, status: list[str]):
    root = Path(root_text)
    if not root.is_dir():
        raise FileNotFoundError(f"Папка документации Directum RX не найдена: {root}")
    words = list(dict.fromkeys(word for word in _WORD_RE.findall(query.casefold())
                              if (len(word) >= 2 or word.isdigit()) and word not in _STOP_WORDS))[:40]
    if not words:
        return ()
    match_query = " OR ".join(f'"{word}"' for word in words)
    with _INDEX_LOCK:
        connection = _connect(_cache_path(root))
        try:
            with connection:
                _refresh_index(root, connection)
            lexical = connection.execute(
                "SELECT rowid, path, title, content FROM chunks WHERE chunks MATCH ? "
                "ORDER BY bm25(chunks, 0.0, 4.0, 1.0) LIMIT 20", (match_query,)
            ).fetchall()
            semantic = []
            if settings.rag_vector_enabled:
                try:
                    semantic = vector_search(connection, query, settings)
                except (VectorSearchError, httpx.HTTPError, ValueError, KeyError) as error:
                    note = f"Векторный поиск недоступен; использован только BM25: {error}"
                    status.append(note)
                    logging.getLogger(__name__).warning(note)
            return fuse_results(lexical, semantic, _RESULT_COUNT)
        finally:
            connection.close()


def build_documentation_tool(docs_root: str | Path, settings: Settings | None = None, *, on_results=None, on_status=None):
    """Create a hybrid documentation retrieval tool."""
    root = Path(docs_root).expanduser().resolve()

    @tool
    def search_directum_documentation(query: str) -> str:
        """Search Directum RX 26.2 documentation for product behavior, configuration, integrations or operations. Use a short query with relevant concepts and exact error names."""
        if not query.strip():
            raise ValueError("Поисковый запрос по документации не может быть пустым")
        status: list[str] = []
        results = search_documentation(root, query, settings=settings, status=status)
        if on_results is not None:
            on_results(results)
        if on_status is not None:
            on_status(status)
        text = format_documentation_results(results) if results else "В документации Directum RX совпадений по этому запросу не найдено."
        return text + ("\n\n" + "\n".join(status) if status else "")

    return search_directum_documentation


def search_documentation(docs_root: str | Path, query: str, *,
                         settings: Settings | None = None, status: list[str] | None = None):
    """Return source path, title and excerpt; optionally report degraded retrieval."""
    root = Path(docs_root).expanduser().resolve()
    try:
        return _search_index(str(root), query[:2000], settings or get_settings(),
                             status if status is not None else [])
    except (OSError, sqlite3.Error) as error:
        raise DocumentationSearchError(
            f"Не удалось выполнить поиск по документации Directum RX: {error}"
        ) from error


def format_documentation_results(
    results: tuple[tuple[str, str, str], ...],
) -> str:
    """Format retrieved excerpts with their exact local source paths."""

    sections = []
    for relative, title, content in results:
        sections.append(
            f"Источник: rx262/{relative}\n"
            f"Раздел: {title[:240]}\n"
            f"Фрагмент:\n{content}"
        )
    return "\n\n---\n\n".join(sections)

"""Build/update the local Directum RX hybrid index; safe to resume."""
import argparse
import json

from app.config import get_settings
from app.documentation_rag import _INDEX_LOCK, _cache_path, _connect, _refresh_index
from app.documentation_vectors import build_vectors


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--query", help="После индексации проверить поиск")
    args = parser.parse_args()
    settings = get_settings()
    root = settings.directum_docs_path.expanduser().resolve()
    if not root.is_dir():
        parser.error(f"Папка справки не найдена: {root}")
    with _INDEX_LOCK:
        connection = _connect(_cache_path(root))
        try:
            with connection:
                # Explicit indexing also detects replacements preserving size/mtime.
                _refresh_index(root, connection, force=True)
            result = build_vectors(connection, settings)
            print(json.dumps(result, ensure_ascii=False), flush=True)
        finally:
            connection.close()
    if args.query:
        from app.documentation_rag import search_documentation, format_documentation_results
        status = []
        print(format_documentation_results(search_documentation(root, args.query, settings=settings, status=status)))
        if status:
            raise RuntimeError("; ".join(status))


if __name__ == "__main__":
    main()

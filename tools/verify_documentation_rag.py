"""Exercise real BGE-M3 retrieval and Qwen3 analysis without touching source logs."""
from time import perf_counter
from app.config import get_settings
from app.agent import analyze_log
from app.documentation_rag import search_documentation


def main():
    settings = get_settings()
    status = []
    start = perf_counter()
    results = search_documentation(settings.directum_docs_path,
        "RabbitMQ connection recovery failed Connection failed port 5672",
        settings=settings, status=status)
    assert results and not status, status
    assert any("ustranenije_oshibok" in row[0] for row in results), results
    print(f"Hybrid retrieval OK: {len(results)} excerpts, {perf_counter() - start:.2f}s", flush=True)
    answer = analyze_log({"message": "Directum RX: RabbitMQ connection 'PreviewService.Host.PublishersConnection' recovery failed.",
        "exception": "System.AggregateException: Connection failed; RabbitMQ port 5672"}, settings=settings)
    assert answer.count("Проверенные страницы локальной документации:") == 1, answer
    assert "Векторный поиск недоступен" not in answer, answer
    print(answer, flush=True)
    print(f"Real RAG + Qwen3 OK: {perf_counter() - start:.2f}s", flush=True)


if __name__ == "__main__":
    main()

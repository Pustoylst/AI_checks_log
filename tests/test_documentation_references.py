import pytest

from app.agent import _enforce_documentation_references


@pytest.mark.parametrize("heading", [
    "Проверенные страницы локальной документации:",
    "### Изученные страницы документации",
    "**Использованные источники документации:**",
    "## Источники",
    "### Документация Directum RX 26.2",
])
def test_model_bibliography_is_replaced_with_one_verified_list(heading):
    response = (
        "Причина: соединение отклонено.\n\n"
        + heading + "\n- `rabbit.htm` — RabbitMQ\n- `invented.htm` — Выдуманная страница\n\n"
        "### Следующие шаги\nПроверьте порт 5672."
    )
    answer = _enforce_documentation_references(
        response, (("rabbit.htm", "RabbitMQ", "text"), ("rabbit.htm", "RabbitMQ", "other chunk")),
        docs_available=True, search_error=None, log_data={},
    )
    assert answer.count("Проверенные страницы локальной документации:") == 1
    assert answer.count("`rabbit.htm`") == 1
    assert "invented.htm" not in answer
    assert "Причина: соединение отклонено." in answer
    assert "### Следующие шаги\nПроверьте порт 5672." in answer


def test_inline_citation_is_preserved_and_formatting_is_idempotent():
    response = "Причина описана в [RabbitMQ](rx262/rabbit.htm)."
    kwargs = dict(results=(("rabbit.htm", "RabbitMQ", "text"),),
                  docs_available=True, search_error=None, log_data={})
    answer = _enforce_documentation_references(response, **kwargs)
    assert response in answer
    assert _enforce_documentation_references(answer, **kwargs) == answer

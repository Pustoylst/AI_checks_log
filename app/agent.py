"""GigaChat agent for Directum log analysis."""

from collections.abc import Callable
import json
from pathlib import Path
import re
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
from langchain_core.runnables import Runnable
from langchain_gigachat.chat_models import GigaChat

from app.config import Settings, get_settings
from app.tools import build_repository_tools
from app.schemas import FixProposal

SYSTEM_PROMPT = """Ты анализируешь логи приложения Directum.
Всегда отвечай только на русском языке, даже если лог или названия инструментов на английском.
Объясняй вероятные причины, ссылайся на конкретные данные из лога и предлагай следующие шаги.
Если в логе упомянут файл, класс, функцию или символ, используй инструменты репозитория для проверки.
Используй результаты инструментов в итоговом ответе и не утверждай, что изучал файлы, которые не читал.
Если исходники недоступны, анализируй только лог и явно сообщи об этом.
Структура ответа: Причины, Доказательства, Ссылки на код, Следующие шаги.
"""

FIX_PROMPT = """Ты готовишь безопасное предложение исправления кода для ошибки Directum.
Отвечай только на русском языке и верни только JSON без markdown с полями:
path, explanation, old_text, new_text.
path должен быть относительным путём к одному исходному файлу.
old_text должен быть точным существующим фрагментом из файла, new_text — его заменой.
Не выдумывай содержимое файла: сначала используй read_git_file.
Не предлагай изменения, если причина недостаточно подтверждена кодом.
"""


def _parse_fix_proposal(response: str) -> FixProposal:
    """Parse strict JSON or JSON wrapped in a markdown response."""

    candidates = [response.strip()]
    candidates.extend(re.findall(r"```(?:json)?\s*(\{.*?\})\s*```", response, flags=re.DOTALL))
    for candidate in candidates:
        try:
            return FixProposal.model_validate(json.loads(candidate))
        except (json.JSONDecodeError, ValueError, TypeError):
            continue
    raise ValueError("Агент не вернул корректное предложение исправления в формате JSON")


def _create_model(settings: Settings, model_name: str) -> GigaChat:
    if not settings.has_gigachat_credentials:
        raise ValueError("GIGACHAT_CREDENTIALS is not configured")
    return GigaChat(
        credentials=settings.gigachat_credentials.get_secret_value(),
        scope=settings.gigachat_scope,
        model=model_name,
        verify_ssl_certs=settings.gigachat_verify_ssl_certs,
        timeout=60,
    )


def _invoke_with_tools(
    model: Runnable,
    tools: list,
    messages: list,
    max_iterations: int,
) -> str:
    tool_map = {item.name: item for item in tools}
    model_with_tools = model.bind_tools(tools)

    for _ in range(max_iterations):
        response = model_with_tools.invoke(messages)
        messages.append(response)
        if not response.tool_calls:
            return str(response.content)

        for tool_call in response.tool_calls:
            tool = tool_map.get(tool_call["name"])
            if tool is None:
                result = f"Unknown tool: {tool_call['name']}"
            else:
                try:
                    result = tool.invoke(tool_call["args"])
                except Exception as error:
                    result = f"Tool error: {error}"
            messages.append(ToolMessage(content=str(result), tool_call_id=tool_call["id"]))

    raise RuntimeError("Agent exceeded the maximum number of tool-call iterations")


def analyze_log(
    log_data: Any,
    repo_root: str | Path | None = None,
    settings: Settings | None = None,
    model_factory: Callable[[Settings, str], Runnable] = _create_model,
    max_iterations: int = 6,
) -> str:
    """Analyze one log using GigaChat and optional repository context."""

    active_settings = settings or get_settings()
    tools = build_repository_tools(repo_root) if repo_root else []
    prompt = (
        "Проанализируй этот JSON-лог. Сохраняй точные сообщения ошибок и временные метки. "
        "Итоговый ответ напиши только на русском языке.\n\n"
        f"{log_data}"
    )
    messages = [SystemMessage(content=SYSTEM_PROMPT), HumanMessage(content=prompt)]

    try:
        model = model_factory(active_settings, active_settings.gigachat_model)
        return _invoke_with_tools(model, tools, messages, max_iterations)
    except Exception as primary_error:
        if not active_settings.has_gigachat_credentials:
            raise
        fallback = model_factory(active_settings, active_settings.gigachat_fallback_model)
        messages.append(
            HumanMessage(content=f"The primary model failed; retry using the fallback model. Error: {primary_error}")
        )
        return _invoke_with_tools(fallback, tools, messages, max_iterations)


def propose_fix(
    log_data: Any,
    repo_root: str | Path,
    settings: Settings | None = None,
    model_factory: Callable[[Settings, str], Runnable] = _create_model,
    max_iterations: int = 6,
) -> FixProposal:
    """Ask the agent for a reviewable fix; this function never writes files."""

    active_settings = settings or get_settings()
    tools = build_repository_tools(repo_root)
    messages = [
        SystemMessage(content=FIX_PROMPT),
        HumanMessage(content=f"Лог и контекст для исправления:\n{log_data}"),
    ]
    try:
        model = model_factory(active_settings, active_settings.gigachat_model)
        response = _invoke_with_tools(model, tools, messages, max_iterations)
    except Exception as primary_error:
        if not active_settings.has_gigachat_credentials:
            raise
        fallback = model_factory(active_settings, active_settings.gigachat_fallback_model)
        messages.append(HumanMessage(content=f"Повтори с fallback-моделью. Ошибка: {primary_error}"))
        response = _invoke_with_tools(fallback, tools, messages, max_iterations)

    try:
        return _parse_fix_proposal(response)
    except ValueError:
        normalization_prompt = """Преобразуй предыдущий ответ в предложение исправления.
Верни только один корректный JSON-объект без markdown и без пояснений:
{"path":"относительный путь","explanation":"краткое объяснение на русском","old_text":"точный фрагмент из файла","new_text":"исправленный фрагмент"}
Обязательно сначала вызови read_git_file для файла, если точный old_text ещё не подтверждён.
Если исправление невозможно уверенно определить, верни JSON с пустыми old_text и new_text.
"""
        messages.append(HumanMessage(content=normalization_prompt))
        normalized_response = _invoke_with_tools(model, tools, messages, max_iterations)
        return _parse_fix_proposal(normalized_response)
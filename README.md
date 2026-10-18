# Directum Log Analyzer

Каркас проекта для анализа JSON-логов Directum с помощью GigaChat. На этапе 0 интерфейс и агент не реализуются: запуск выполняется из Python-кода.

## Требования

- Python 3.11+
- credentials GigaChat для проверки доступа к API

## Установка

```bash
cd PP
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
cp .env.example .env
```

Заполните `GIGACHAT_CREDENTIALS` в `.env`. Файл `.env` игнорируется Git и не должен добавляться в репозиторий.

## Проверка конфигурации

```bash
python -m tools.check_config
```

Команда проверяет наличие credentials и выводит выбранную модель, fallback-модель и TLS-настройку, не печатая секрет.

Проверка текущего Python-каркаса:

```bash
python -m app.main
pytest
```

## Настройки

- `GIGACHAT_CREDENTIALS` — обязательны для вызовов GigaChat.
- `GIGACHAT_SCOPE` — по умолчанию `GIGACHAT_API_PERS`.
- `GIGACHAT_MODEL` — по умолчанию `GigaChat-2-Max`.
- `GIGACHAT_FALLBACK_MODEL` — по умолчанию `GigaChat-2`.
- `GIGACHAT_VERIFY_SSL_CERTS` — для локальной разработки по умолчанию `false`.

## Структура

- `app/` — код приложения и конфигурация.
- `tools/` — запускаемые утилиты проекта.
- `static/` — зарезервировано под будущий интерфейс.
- `tests/` — тесты.

# Directum Log Analyzer

Сервис для анализа JSON-логов системы Directum с помощью GigaChat. Пользователь передаёт лог, агент определяет вероятные причины ошибки, при необходимости читает исходный код репозитория и формирует итоговый ответ на русском языке.

Проект запускается локально через Python и FastAPI. Встроенный интерфейс доступен на главной странице сервера.

## Возможности MVP

- анализ непустого JSON-объекта с логом;
- работа без обязательных полей `trace_id` и `repo_paths`;
- основная модель `GigaChat-2-Max` и fallback `GigaChat-2`;
- инструменты `read_git_file` и `search_code_in_repo`;
- защита инструментов от выхода за пределы корня репозитория;
- HTTP endpoint `POST /analyze` и проверка `GET /health`;
- ответы агента на русском языке;
- обработка пустого и невалидного JSON;
- предложение исправления с предпросмотром;
- применение исправления только после явного подтверждения;
- резервная копия файла перед записью;
- тесты без обращения к реальному API через fake-модель.

## Что не входит в текущий MVP

- RAG и векторные базы данных;
- MCP-сервер;
- поддержка скриншотов;
- мультиагентная архитектура;
- автоматическое исправление кода;
- постоянный фоновый сервис.

## Требования и установка

- Python 3.11 или новее;
- credentials GigaChat;
- доступ к сети для запроса к GigaChat.

```bash
cd /Users/dima/Documents/programming/PP
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
cp .env.example .env
```

Для Windows используйте `.venv\\Scripts\\activate` вместо `source`.

## Настройка GigaChat

В `.env` укажите:

```env
GIGACHAT_CREDENTIALS=ваша_строка_credentials
GIGACHAT_SCOPE=GIGACHAT_API_PERS
GIGACHAT_MODEL=GigaChat-2-Max
GIGACHAT_VERIFY_SSL_CERTS=false

# Необязательная GitHub-интеграция; пустые значения сохраняют локальный режим.
GITHUB_TOKEN=
GITHUB_REPOSITORY=owner/repository
GITHUB_API_URL=https://api.github.com
GITHUB_DEFAULT_BRANCH=main
CI_POLL_INTERVAL_SECONDS=60
```

`GIGACHAT_CREDENTIALS` — секрет авторизации. `.env` добавлен в `.gitignore` и не должен публиковаться. При утечке credentials перевыпустите ключ в кабинете GigaChat.

Проверка настроек:

```bash
python -m tools.check_config
```

Команда не печатает сам секрет.

## Запуск через CLI

Пример `sample_log.json`:

```json
{
	"timestamp": "2026-10-20T12:00:00Z",
	"level": "ERROR",
	"message": "Directum request failed with timeout",
	"file": "app/agent.py"
}
```

Анализ только по логу:

```bash
python -m tools.analyze_json sample_log.json
```

Анализ с доступом к исходному коду:

```bash
python -m tools.analyze_json sample_log.json --repo /Users/dima/Documents/programming/PP
```

Ответ появляется в терминале. Процесс завершается после одного анализа и не работает постоянно.

## Запуск HTTP API

В первом терминале:

```bash
cd /Users/dima/Documents/programming/PP
source .venv/bin/activate
uvicorn app.api:app --reload
```

Сервер работает по адресу `http://127.0.0.1:8000`, пока выполняется команда `uvicorn`. Остановка: `Ctrl+C`. Флаг `--reload` перезапускает сервер после изменения Python-файлов.

Откройте в браузере `http://127.0.0.1:8000/`. На странице можно выбрать JSON-файл, указать корень репозитория и нажать «Проверить лог». Результат появится ниже формы, без перезагрузки страницы.

Во втором терминале:

```bash
curl http://127.0.0.1:8000/health
```

Ожидаемый ответ: `{"status":"ok"}`.

Анализ файла:

```bash
curl -X POST \
	-F "file=@/Users/dima/Documents/programming/PP/sample_log.json" \
	"http://127.0.0.1:8000/analyze?repo=/Users/dima/Documents/programming/PP"
```

Ответ содержит поле `result` с русскоязычным анализом. Ошибка `curl (7)` означает, что сервер не запущен, ошибка `curl (26)` — что файл не найден в текущем каталоге.

## HTTP API

### `GET /health`

Проверяет, что сервер запущен.

### `POST /analyze`

Принимает multipart-поля:

- `file` — обязательный JSON-файл;
- `repo` — необязательный путь к корню репозитория.

Входной JSON должен быть непустым объектом. Поля `timestamp`, `level`, `message`, `trace_id` и `repo_paths` поддерживаются явно, остальные поля разрешены.

Коды ошибок: `400` — пустой файл/объект или невалидный JSON; `422` — ошибка структуры; `503` — отсутствуют credentials; `504` — таймаут GigaChat; `502` — другая ошибка внешнего вызова.

### `POST /propose-fix`

Получает JSON-лог и обязательный параметр `repo`. Агент возвращает объяснение и точную замену `old_text` на `new_text` в одном файле. Этот endpoint ничего не меняет на диске.

### `POST /apply-fix?repo=...`

Принимает предложение и поле `approved`. Изменение применяется только при `approved: true`; сервер повторно проверяет путь, наличие исходного фрагмента ровно один раз и создаёт резервную копию рядом с исходным файлом. При `approved: false` возвращается `403`, файл не меняется.

В интерфейсе workflow выглядит так: анализ лога → «Предложить исправление» → просмотр diff → «Применить изменение».

### `GET /repository/status?repo=...`

Возвращает текущую ветку, `origin` и список локальных изменений. Работает без GitHub token.

### `GET /ci/checks?ref=...`

Читает GitHub Checks API для `GITHUB_REPOSITORY`. Требует `GITHUB_TOKEN` и `GITHUB_REPOSITORY`; без них возвращает `503`.

### `POST /git/commit-push?repo=...`

Создаёт commit и отправляет его в `origin` только при `approved: true`. В запросе нужно явно перечислить файлы:

```json
{
	"approved": true,
	"paths": ["app/service.py", "tests/test_service.py"],
	"message": "fix: handle Directum timeout"
}
```

### `POST /git/merge?repo=...`

Выполняет merge source-ветки в target и push только при `approved: true`.

Текущий слой подключает Git и читает статусы CI, но постоянный watcher, загрузка логов GitHub Actions и автоматическое создание pull request ещё являются следующим этапом. Сервер не коммитит и не мержит код без явного решения пользователя.

## Архитектура

```text
JSON-файл / UploadFile -> LogPayload -> analyze_log -> GigaChat
																										 |
												 read_git_file/search_code_in_repo
																										 |
																						 ответ на русском
```

- `app/config.py` — настройки из окружения;
- `app/schemas.py` — модели входных данных;
- `app/api.py` — FastAPI endpoint;
- `app/agent.py` — промпт, модели и цикл `tool_calls`;
- `app/tools.py` — безопасное чтение и поиск по репозиторию;
- `tools/analyze_json.py` — CLI-анализ JSON;
- `tools/check_config.py` — проверка конфигурации;
- `tests/` — автоматические тесты.

Инструменты вызываются напрямую из Python, MCP-сервер не используется.

## Тестирование

```bash
pytest -q
```

Проверяются конфигурация, path traversal, поиск и чтение кода, вызов инструмента агентом, fallback-модель, API, Git status, запрет commit/merge без approval, невалидный JSON, отсутствие `trace_id`/`repo_paths`, отказ без подтверждения, точная замена и backup. Live-запросы к GigaChat в `pytest` не включены, чтобы тесты были быстрыми и воспроизводимыми.

## Методика проверки агента

### 1. Автоматическая проверка

```bash
source .venv/bin/activate
pytest -q
```

Ожидается успешное прохождение всех тестов. Это проверяет логику инструментов, цикл `tool_calls`, fallback, API и безопасность применения исправления.

### 2. Проверка реального анализа

Запустите сервер:

```bash
uvicorn app.api:app --reload
```

Откройте `http://127.0.0.1:8000/`, загрузите `sample_log.json` и укажите корень проекта. Проверьте, что ответ:

- написан на русском языке;
- содержит причины и доказательства;
- ссылается на `app/agent.py`, если модель вызвала инструмент;
- не падает без `trace_id` и `repo_paths`.

### 3. Безопасная проверка исправления

Не используйте для первого теста настоящий проект. Создайте временный репозиторий:

```bash
mkdir -p /tmp/directum-agent-fixture
printf 'TIMEOUT = 60\\n' > /tmp/directum-agent-fixture/service.py
```

Создайте `fix_log.json`:

```json
{
	"level": "ERROR",
	"message": "Request timeout because service.py uses too small timeout",
	"file": "service.py"
}
```

В интерфейсе укажите `/tmp/directum-agent-fixture` как корень репозитория. После анализа нажмите «Предложить исправление» и проверьте, что показаны файл и пары «Было/Станет». До нажатия «Применить изменение» содержимое `service.py` не должно меняться.

После подтверждения проверьте:

```bash
cat /tmp/directum-agent-fixture/service.py
ls /tmp/directum-agent-fixture/*.backup-*
```

Ожидается новая строка в `service.py` и резервная копия со старым содержимым. Для проверки защиты отправьте путь `../../etc/passwd`: сервер должен отказать и не изменить файл.

### 4. Проверка ошибок

Проверьте отдельно пустой файл, невалидный JSON и остановленный сервер. Ожидаемые результаты: понятная ошибка в интерфейсе, HTTP `400` для плохого JSON и ошибка подключения `curl`, если `uvicorn` не запущен.

## Демонстрация

```bash
python -m tools.check_config
pytest -q
uvicorn app.api:app --reload
```

В браузере откройте `http://127.0.0.1:8000/`, загрузите `sample_log.json`, укажите путь `/Users/dima/Documents/programming/PP` и нажмите «Проверить лог». Перед демонстрацией также удобно показать `/health` и русскоязычный результат через `curl`.

## Дальнейшие этапы

1. Проверить качество на 3–5 реалистичных Directum-логах.
2. Улучшить формат ссылок на строки исходного кода.
3. Добавить лимит размера файла и безопасное журналирование.
4. Добавить историю результатов текущей сессии.
5. Подготовить скриншот и финальное описание архитектуры.

# Context7 MCP Integration

## Описание

Context7 MCP интеграция обеспечивает доступ к актуальной документации и примерам кода для множества библиотек. Документация берется прямо из исходников, что гарантирует актуальность и отсутствие устаревшей информации.

## Возможности

- **Актуальная документация**: Документация берется из официальных источников
- **Примеры кода**: Готовые примеры кода для использования
- **Множество библиотек**: Поддержка популярных Python библиотек
- **Интеграция с Knowledge Bridge**: Совместная работа с внутренними стандартами

## Установка

### Требования

- Node.js >= v18.0.0
- Python 3.10+
- MCP клиент (Claude Code, Claude Desktop, Cursor, и т.д.)

### API Ключ Context7

Для повышенных лимитов запросов рекомендуется получить бесплатный API ключ:

1. Перейдите на https://context7.com/dashboard
2. Зарегистрируйтесь
3. Получите API ключ
4. Добавьте в `.env`:

```env
CONTEXT7_API_KEY=your-api-key-here
```

## Использование

### В коде

```python
from src.host_orchestrator import ContextOrchestrator

# Включите Context7
orchestrator = ContextOrchestrator(
    enable_context7=True
)

await orchestrator.connect()

# Получить список библиотек
libs = await orchestrator.list_supported_libraries()

# Запросить документацию
docs = await orchestrator.query_library_docs(
    "torch",
    "create tensors and perform operations"
)

# Получить примеры кода
examples = await orchestrator.get_library_examples(
    "fastapi",
    "JWT authentication"
)

await orchestrator.disconnect()
```

### В интерактивном режиме

Запустите интерактивную сессию:

```bash
python src/host_orchestrator.py
```

Доступные команды:
- `ctx7-libs` - Список поддерживаемых библиотек
- `ctx7-docs <lib> <query>` - Запросить документацию
- `ctx7-ex <lib> <topic>` - Получить примеры кода

## Поддерживаемые библиотеки

| Библиотека | Context7 ID | Назначение |
|-------------|--------------|------------|
| torch | /pytorch/pytorch | Глубокое обучение |
| transformers | /huggingface/transformers | NLP модели |
| diffusers | /huggingface/diffusers | Diffusion модели |
| fastapi | /tiangolo/fastapi | API фреймворк |
| anthropic | /anthropics/anthropic-sdk-python | Anthropic API |
| openai | /openai/openai-python | OpenAI API |
| redis | /redis/redis-py | Redis клиент |
| postgresql | /psycopg/psycopg | PostgreSQL драйвер |
| pillow | /python-pillow/Pillow | Изображения |
| requests | /psf/requests | HTTP запросы |
| pytest | /pytest-dev/pytest | Тестирование |
| celery | /celery/celery | Task queue |
| numpy | /numpy/numpy | Численные вычисления |
| pandas | /pandas-dev/pandas | Анализ данных |
| scipy | /scipy/scipy | Научные вычисления |
| asyncio | /python/cpython | Асинхронный Python |

## Инструменты

### resolve_library_id

Разрешает имя библиотеки в Context7 ID.

```python
library_id = await orchestrator.resolve_library_id(
    library_name="torch",
    query="tensor operations"
)
# Возвращает: /pytorch/pytorch
```

### query_library_docs

Получает документацию и примеры для библиотеки.

```python
docs = await orchestrator.query_library_docs(
    library="fastapi",
    query="OAuth2 authentication middleware"
)
# Возвращает: Документацию с примерами кода
```

### get_library_examples

Получает только примеры кода.

```python
examples = await orchestrator.get_library_examples(
    library="torch",
    topic="neural network creation"
)
# Возвращает: Список примеров кода
```

### list_supported_libraries

Возвращает список всех поддерживаемых библиотек.

```python
libs = await orchestrator.list_supported_libraries()
# Возвращает: Словарь с информацией о библиотеках
```

## Примеры использования

### Пример 1: Настройка FastAPI с JWT

```python
orchestrator = ContextOrchestrator(enable_context7=True)
await orchestrator.connect()

# Получить актуальную документацию
docs = await orchestrator.query_library_docs(
    "fastapi",
    "JWT authentication setup"
)

# Использовать полученную документацию для настройки
```

### Пример 2: Создание PyTorch модели

```python
# Получить примеры создания нейросети
examples = await orchestrator.get_library_examples(
    "torch",
    "CNN model definition"
)

for example in examples:
    print(example)
```

### Пример 3: Совместная работа с Knowledge Bridge

```python
orchestrator = ContextOrchestrator(
    enable_knowledge_bridge=True,
    enable_context7=True
)

await orchestrator.connect()

# Получить внутренний стандарт
kb_standard = await orchestrator.search_standard("api", "authentication")

# Получить актуальную документацию
ctx7_docs = await orchestrator.query_library_docs("fastapi", "auth")

# Комбинировать оба источника
```

## Тестирование

Запуск тестов Context7 интеграции:

```bash
python tests/test_context7_integration.py
```

Тесты проверяют:
- Подключение к Context7 MCP серверу
- Разрешение ID библиотек
- Запрос документации
- Получение примеров кода
- Список поддерживаемых библиотек
- Совместную работу с Knowledge Bridge

## Траблшутинг

### Проблема: Context7 недоступен

Убедитесь, что:
1. Node.js установлен: `node --version` (>= v18.0.0)
2. API ключ указан в `.env` (для повышенных лимитов)
3. Интернет-соединение активно

### Проблема: Документация не загружается

Проверьте:
1. Правильность имени библиотеки
2. Корректность запроса
3. Доступность Context7 API

### Проблема: Слишком медленные запросы

1. Получите API ключ для повышенных лимитов
2. Используйте кэширование результатов
3. Уменьшите количество параллельных запросов

## Архитектура

```
+---------------------+
|  Host Orchestrator |
+----------+----------+
           |
           | (MCP stdio)
           |
    +------v------+
    | Context7    |
    | MCP Server   |
    +------+------+
           |
           | (HTTP / CLI)
           |
    +------v------+
    | Context7    |
    | API Service  |
    +-------------+
```

## Ограничения

- Требуется интернет-соединение для запросов
- API ключи повышают лимиты запросов
- Не все библиотеки могут быть доступны
- Зависит от актуальности внешних источников

## Будущие улучшения

- [ ] Локальное кэширование документации
- [ ] Офлайн режим для популярных библиотек
- [ ] Поддержка дополнительных языков (JavaScript, Go, Rust)
- [ ] Автоматическое обновление документации
- [ ] Интеграция с IDE (VS Code, PyCharm)

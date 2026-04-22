# MCP Context Pipeline

ML-пайплайн для управления контекстом в MCP (Model Context Protocol) приложениях с автоматическим маскированием PII.

## Описание

Решение разработано Senior ML-Engineer с учетом кроссплатформенности:
- **Windows** — локальная разработка
- **Ubuntu/Linux** — продакшен/серверное окружение

Архитектура основана на **Docker Compose** для изоляции сервисов (Linux) и **Python-скриптов**, которые могут запускаться как локально (через stdio), так и внутри контейнеров (через SSE).

## Ключевые возможности

### 🛡️ Безопасность (Security Phase 3)
- **PII Guard**: Автоматическое маскирование персональных данных перед отправкой в LLM
- **Microsoft Presidio**: Индустриальный стандарт для De-identification
- **Поддержка РФ**: Распознавание паспортов, ИНН, российских телефонов
- **Secure Middleware**: Прокси-класс для безопасного взаимодействия с LLM

### 📊 Управление контекстом
- **AC1**: Автоматическое сжатие контекста при превышении порога
- **AC2**: Инициативная суммаризация агентом
- **AC3**: Инъекция временного контекста
- **AC4**: Управление состоянием сессии (чекпоинты)
- **AC5**: Стресс-тестирование на 100k+ токенов

### 🔗 Knowledge Bridge (Context 7 Integration)
- **search_standard**: Поиск стандартов в базе знаний компании
- **list_domains**: Список доступных доменов знаний
- **Resources**: Архитектурные принципы и технологический стек
- **get_best_practices**: Получение лучших практик для домена
- **Комплаенс**: Соответствие внутренним стандартам компании

### 📚 Context7 MCP (Актуальная документация)
- **resolve_library_id**: Разрешение имени библиотеки в Context7 ID
- **query_docs**: Получение документации и примеров кода
- **get_library_examples**: Получение примеров кода для библиотеки
- **list_supported_libraries**: Список поддерживаемых библиотек
- **Поддерживаемые библиотеки**: torch, transformers, diffusers, fastapi, anthropic, openai, redis, postgresql, pillow, requests, pytest, celery, numpy, pandas, scipy

### 🔧 Мультипровайдерность
- **Anthropic Claude**: claude-sonnet-4-20250514 (по умолчанию)
- **OpenAI GPT**: gpt-4o/gpt-4o-mini
- **Легкое переключение** через переменные окружения

## Структура проекта

```
/mcp_context_pipeline
|-- docker-compose.yml       # Оркестрация БД и Redis
|-- .env                     # Конфигурация (API ключи, настройки)
|-- .env.example             # Пример конфигурации
|-- requirements.txt         # Зависимости Python
|-- src/
|   |-- server.py            # MCP-сервер с PII Guard
|   |-- host_orchestrator.py # Логика Хоста (AC1, AC3, AC4, Knowledge Bridge, Context7)
|   |-- knowledge_server.py  # MCP-сервер Context 7 (Knowledge Bridge)
|   |-- context7_mcp_server.py # MCP-сервер Context7 для библиотек 📚
|   |-- utils.py             # Утилиты (Tiktoken, helpers)
|   |-- pii_guard.py         # Модуль маскирования PII 🛡️
|   |-- secure_middleware.py # Безопасный прокси для LLM 🛡️
|   |-- test_pipeline.py     # Тесты AC1-AC5
|   |-- test_compression.py  # Тест сжатия контекста
|-- tests/
|   |-- run_all_tests.py     # Мастер-скрипт запуска всех тестов
|   |-- test_context_management.py   # Epic 1: Управление контекстом
|   |-- test_security_pii.py        # Epic 2: Безопасность и PII
|   |-- test_performance_infra.py   # Epic 3: Производительность
|   |-- test_model_evaluation.py    # Epic 4: Оценка качества
|   |-- test_knowledge_bridge.py   # Epic 5: Knowledge Bridge
|   |-- test_pii_completeness.py    # Тест на 100 шаблонов PII 🛡️
|   |-- test_pii_integration.py     # Интеграционный тест PII 🛡️
|   |-- test_russian_pii.py        # Российские сущности 🛡️
|-- docs/
|   |-- PII_GUARD.md        # Документация PII Guard 🛡️
|-- run_host.bat             # Скрипт запуска для Windows
|-- run_host.sh              # Скрипт запуска для Linux
|-- verify_setup.py          # Проверка установки
|-- README.md                # Этот файл
```

## Установка и запуск

### Требования

- Python 3.10+
- Docker и Docker Compose
- Anthropic API ключ (или OpenAI API ключ)

### Шаг 1: Запуск инфраструктуры (Redis, PostgreSQL)

```bash
docker compose up -d
```

Проверьте статус:
```bash
docker compose ps
```

### Шаг 2: Установка зависимостей Python

```bash
pip install -r requirements.txt
```

### Шаг 3: Настройка переменных окружения

Скопируйте пример и отредактируйте:

```bash
cp .env.example .env
```

Отредактируйте `.env`:
```env
# LLM Provider (anthropic или openai)
LLM_PROVIDER=anthropic

# API ключи
ANTHROPIC_API_KEY=sk-ant-ваш-ключ-claude
OPENAI_API_KEY=sk-ваш-ключ-openai

# Настройки контекста
MAX_TOKENS=128000
SUMMARY_THRESHOLD=100000

# Безопасность
ENABLE_PII_MASKING=true

# Прокси (для обхода региональных ограничений LLM API)
# Примеры:
# HTTP_PROXY=http://username:password@proxy.example.com:8080
# HTTP_PROXY=socks5://127.0.0.1:1080
# HTTP_PROXY=http://localhost:7890
HTTP_PROXY=
HTTPS_PROXY=
ALL_PROXY=

# VLESS (Hiddify, V2Ray) - для надежного обхода ограничений
# Запустите: ./run_vless.sh start
VLESS_URL=
VLESS_SUBSCRIPTION=
VLESS_SERVER_INDEX=0
XRAY_SOCKS_PORT=10809
XRAY_HTTP_PORT=10808
```

**Важно**: Если вы находитесь в регионе, где Anthropic/OpenAI API недоступны, настройте прокси.

**Варианты настройки прокси:**
1. **VLESS/Hiddify** (рекомендуется) - см. [docs/VLESS_HIDDIFY_SETUP.md](docs/VLESS_HIDDIFY_SETUP.md)
2. **Прямой прокси** - см. [docs/PROXY_CONFIGURATION.md](docs/PROXY_CONFIGURATION.md)

### Шаг 4: Проверка установки

```bash
python verify_setup.py
```

### Шаг 5: Запуск

#### Linux/Mac:
```bash
chmod +x run_host.sh
./run_host.sh
```

#### Windows:
```cmd
run_host.bat
```

Или напрямую запустите тест:
```bash
python src/test_pipeline.py 4
```

## Тестирование

### Основные тесты

1. **Базовый функциональный тест** — проверяет основные функции
2. **Стресс-тест** — генерирует 100k+ токенов и проверяет AC1
3. **Тест восстановления чекпоинтов** — проверяет AC4
4. **Все тесты** — запускает все тесты последовательно
5. **Интерактивный режим** — диалог для ручного тестирования

### Запуск основных тестов

```bash
# Запуск конкретного теста
python src/test_pipeline.py 1  # Базовый тест
python src/test_pipeline.py 2  # Стресс-тест
python src/test_pipeline.py 3  # Тест чекпоинтов
python src/test_pipeline.py 4  # Все тесты
python src/test_pipeline.py 5  # Интерактивный режим
```

### Полные тестовые наборы (Epic-based)

#### Epic 1: Управление контекстом
```bash
python tests/test_context_management.py
```

Покрывает:
- US-001: Автоматическое сжатие по порогу
- US-002: Ручной триггер сжатия
- US-003: Инъекция временных меток
- US-004: Создание и восстановление чекпоинтов
- US-005: Семантический поиск в памяти
- US-001.1: Проверка галлюцинаций после сжатия
- US-004.1: Race condition в Redis

#### Epic 2: Безопасность и PII
```bash
python tests/test_security_pii.py
```

Покрывает:
- US-006: Маскирование email адресов
- US-007: Маскирование телефонов (RU/Intl)
- US-008: Маскирование паспортных данных (РФ)
- US-009: Маскирование имен (NER)
- US-010: Проверка утечек (100 шаблонов)
- US-011: Обработка сложных адресов
- Дополнительные тесты: de-masking атаки, obfuscated форматы, сохранение контекста

#### Epic 3: Производительность и Инфраструктура
```bash
python tests/test_performance_infra.py
```

Покрывает:
- US-012: Нагрузочный тест (100k+ токенов)
- US-012.1: Проверка утечек памяти (Memory Leak)
- US-013: Точность подсчета токенов (<5% ошибки)
- US-023: Целостность данных в ClickHouse (Audit Log)
- Дополнительные тесты: latency metrics, concurrent requests

#### Epic 4: Оценка качества и A/B тестирование
```bash
python tests/test_model_evaluation.py
```

Покрывает:
- US-023: Параллельный запуск (Shadow Mode)
- US-024: Метрика семантической близости
- US-025: Стоимость и задержка (Cost/Latency)
- US-026: Мультиязычный стресс-тест
- US-027: Tool Calling Accuracy
- Дополнительные тесты: fidelity после сжатия

#### Epic 5: Knowledge Bridge (Context 7 Integration)
```bash
python tests/test_knowledge_bridge.py
```

Покрывает:
- search_standard: Поиск стандартов в Context 7
- list_domains: Список доменов знаний
- kb://architecture/principles: Архитектурные принципы
- kb://tech_stack: Технологический стек
- kb://coding_standards/python: Python стандарты
- kb://security/guidelines: Рекомендации по безопасности
- get_best_practices: Лучшие практики для домена
- Интеграционные тесты с Context 7

#### Epic 6: Context7 MCP Integration
```bash
python tests/test_context7_integration.py
```

Покрывает:
- Подключение к Context7 MCP серверу
- Разрешение ID библиотек
- Запрос документации
- Получение примеров кода
- Список поддерживаемых библиотек
- Совместная работа с Knowledge Bridge

#### Epic 7: REST API Quality Metrics
```bash
python run_rest_api_eval.py
```

Покрывает:
- Ресурсный подход (resource-oriented URLs)
- Пагинация (limit/offset, page/size)
- Версионность (path, header, query)
- Коды ошибок (2xx, 4xx, 5xx)
- Структурная избыточность (data/meta/errors)

Метрики:
- resource_orientation: >= 0.8
- pagination: >= 0.7
- versioning: >= 0.6
- error_codes: >= 0.7
- structural_redundancy: >= 0.6
- overall_score: >= 0.7

Артефакты:
- artifacts/rest_api_eval/rest_api_eval_report.json
- artifacts/rest_api_eval/rest_api_eval.prom
- artifacts/rest_api_eval/rest_api_eval_summary.txt

### Unified Evaluation

Запуск объединенной оценки внешних знаний и REST API:

```bash
# Запуск с указанием датасетов
EVAL_DATASET_PATH=eval_queries_v3.jsonl REST_API_EVAL_DATASET=data/rest_api_eval_good.jsonl python run_unified_eval.py

# Или через .env
# Установите EVAL_DATASET_PATH и REST_API_EVAL_DATASET в .env
python run_unified_eval.py
```

Артефакты:
- artifacts/unified_eval/unified_eval_report.json
- artifacts/unified_eval/unified_eval_summary.txt

### Запуск всех тестов

```bash
# Запуск всех эпиков последовательно
python tests/run_all_tests.py
```

### CI/CD Integration

Проект использует GitHub Actions для автоматического запуска оценок:

**Workflows:**
- `external_knowledge_eval` - оценка внешних знаний
- `rest_api_eval` - оценка REST API качества
- `unified_eval` - объединенная оценка с комментарием в PR

**Триггеры:**
- Manual запуск через GitHub Actions UI
- Push в соответствующие директории
- Pull request (с автоматическим комментарием)

**Gate checks:**
- External Knowledge: Recall@K >= 0.60, MRR >= 0.45, Latency P95 <= 8000ms
- REST API: Overall Score >= 0.7, Pagination >= 0.7, Resource Orientation >= 0.8

Подробнее: `docs/CI_CD_INTEGRATION.md`

Важно:
- `tests/` — целевой, поддерживаемый набор регрессионных и интеграционных тестов.
- `test_*.py` в корне проекта и `src/test_*.py` — операционные/отладочные проверки (smoke/debug), они не считаются основным CI-набором.
- Для `pytest` по умолчанию ограничен `testpaths = tests` (см. `pytest.ini`).

### Тесты PII Guard 🛡️

1. **Тест полноты на 100 шаблонов** — проверяет все типы сущностей
2. **Интеграционный тест** — проверяет работу PII в контексте сжатия

```bash
# Тест на 100 шаблонов
python tests/test_pii_completeness.py --count 100

# Быстрый тест (20 шаблонов)
python tests/test_pii_completeness.py --count 20 --quiet

# Интеграционный тест
python tests/test_pii_integration.py
```

### Пример работы PII Guard

```python
from src.pii_guard import get_pii_guard

guard = get_pii_guard()

text = "Меня зовут Иван Иванов, телефон +7 (999) 123-45-67, email ivan@example.com"
masked = guard.mask(text, language='en')

print(masked)
# Output: Меня зовут [MASKED_NAME], телефон [MASKED_PHONE], email [MASKED_EMAIL]
```

### Knowledge Bridge (Context 7)

Knowledge Bridge обеспечивает интеграцию с внешними знаниями через MCP-протокол.

```python
from src.host_orchestrator import ContextOrchestrator

orchestrator = ContextOrchestrator(enable_knowledge_bridge=True)

await orchestrator.connect()

# Поиск стандарта в Context 7
standard = await orchestrator.search_standard("api", "pagination")
print(standard)

# Получить список доменов знаний
domains = await orchestrator.list_knowledge_domains()
print(domains)

# Получить лучшие практики
practices = await orchestrator.get_best_practices("security")
print(practices)

await orchestrator.disconnect()
```

### Доступные ресурсы Knowledge Bridge

- `kb://architecture/principles` - Архитектурные принципы компании
- `kb://tech_stack` - Актуальный технологический стек
- `kb://coding_standards/python` - Python стандарты кода
- `kb://security/guidelines` - Рекомендации по безопасности

### Доступные инструменты Knowledge Bridge

- `search_standard(domain, topic)` - Поиск стандарта по домену и теме
- `list_domains()` - Список доступных доменов знаний
- `get_best_practices(domain)` - Лучшие практики для домена

### Context7 MCP (Актуальная документация)

Context7 MCP обеспечивает доступ к актуальной документации и примерам кода для множества библиотек.

```python
from src.host_orchestrator import ContextOrchestrator

orchestrator = ContextOrchestrator(enable_context7=True)

await orchestrator.connect()

# Получить список поддерживаемых библиотек
libs = await orchestrator.list_supported_libraries()
print(libs)

# Запросить документацию
docs = await orchestrator.query_library_docs("torch", "tensor operations")
print(docs)

# Получить примеры кода
examples = await orchestrator.get_library_examples("fastapi", "authentication")
print(examples)

await orchestrator.disconnect()
```

### Поддерживаемые библиотеки Context7

| Библиотека | Context7 ID | Описание |
|-------------|--------------|-----------|
| torch | /pytorch/pytorch | PyTorch - библиотека глубокого обучения |
| transformers | /huggingface/transformers | Hugging Face Transformers |
| diffusers | /huggingface/diffusers | Diffusion модели |
| fastapi | /tiangolo/fastapi | FastAPI - фреймворк для API |
| anthropic | /anthropics/anthropic-sdk-python | Anthropic SDK |
| openai | /openai/openai-python | OpenAI Python SDK |
| redis | /redis/redis-py | Redis Python клиент |
| postgresql | /psycopg/psycopg | PostgreSQL драйвер |
| pillow | /python-pillow/Pillow | Pillow - обработка изображений |
| requests | /psf/requests | HTTP библиотека |
| pytest | /pytest-dev/pytest | Тестовый фреймворк |
| celery | /celery/celery | Celery - task queue |
| numpy | /numpy/numpy | NumPy - численные вычисления |
| pandas | /pandas-dev/pandas | Pandas - анализ данных |
| scipy | /scipy/scipy | SciPy - научные вычисления |

### Доступные инструменты Context7

- `resolve_library_id(library_name, query)` - Разрешить имя библиотеки в Context7 ID
- `query_library_docs(library, query)` - Получить документацию и примеры
- `get_library_examples(library, topic)` - Получить примеры кода
- `list_supported_libraries()` - Список поддерживаемых библиотек

### Использование в интерактивном режиме

В интерактивном режиме доступны команды:
- `ctx7-libs` - Список поддерживаемых библиотек
- `ctx7-docs <lib> <query>` - Запросить документацию
- `ctx7-ex <lib> <topic>` - Получить примеры кода

### Результаты тестов Russian PII

```
Total Tests: 84
Successful: 84 (100.0%)
Failed: 0
Leakage Detected: 0

Entity Detection Statistics:
  PERSON                   :  72
  PHONE_NUMBER             :  34
  RU_PHONE                 :  25
  DATE_TIME                :  22
  RU_PASSPORT              :  20
  DRIVER_LICENSE_RF        :  20
  BANK_ACCOUNT             :  15
  TELEGRAM_HANDLE          :  14
  RU_INN                   :  12
  CREDIT_CARD              :  11
  EMAIL_ADDRESS            :   8
  SNILS                    :   8
  BIC_CODE                 :   7
  VEHICLE_PLATE            :   5
  VK_PROFILE               :   5
  MEDICAL_POLICY           :   5
```

**Особенности:**
- Поддержка сложных русских имен с дефисами (Иванов-Смирнов, Анна-Мария)
- Все форматы российских телефонов (+7/8, с/без пробелов, скобок, дефисов)
- 100% детекция всех российских сущностей из конфигурации

## Архитектура

### Инфраструктура (Docker Compose)

- **Redis** — для сессий, кэша и хранения саммари (Memory Service)
- **PostgreSQL** — для долгосрочной памяти (Facts)

### Knowledge Bridge (knowledge_server.py)

MCP-сервер для интеграции с внешними знаниями (Context 7):

**Инструменты:**
- `search_standard` — поиск стандартов в Context 7
- `list_domains` — список доступных доменов знаний
- `get_best_practices` — лучшие практики для домена

**Ресурсы:**
- `kb://architecture/principles` — архитектурные принципы
- `kb://tech_stack` — технологический стек
- `kb://coding_standards/python` — Python стандарты
- `kb://security/guidelines` — рекомендации по безопасности

**Домены знаний:**
- api — стандарты API (пагинация, обработка ошибок)
- security — безопасность (аутентификация, шифрование)
- db — база данных (транзакции, миграции)
- python — Python (стиль, типизация, async)
- deployment — деплоймент (CI/CD, контейнеры)

### Context7 MCP Server (context7_mcp_server.py)

MCP-сервер для интеграции с Context7 — получение актуальной документации:

**Инструменты:**
- `resolve_library_id` — разрешить имя библиотеки в Context7 ID
- `query_docs` — получить документацию и примеры кода
- `get_library_examples` — получить только примеры кода
- `list_supported_libraries` — список поддерживаемых библиотек
- `get_best_practices` — лучшие практики для библиотеки
- `check_version_compatibility` — проверить совместимость версии

**Ресурсы:**
- `ctx7://libraries` — информация о поддерживаемых библиотеках
- `ctx7://query/<library>/<topic>` — быстрый запрос документации

**Поддерживаемые библиотеки:**
torch, transformers, diffusers, fastapi, anthropic, openai, redis, postgresql, pillow, requests, pytest, celery, numpy, pandas, scipy, asyncio

### MCP-сервер (server.py)

Реализует инструменты и ресурсы MCP:
- `compress_context` — сжатие контекста с автоматическим PII маскированием
- `save_checkpoint` — сохранение состояния
- `load_checkpoint` — восстановление состояния
- `search_memory` — поиск по памяти
- Ресурсы для времени и лимитов

### Хост-оркестратор (host_orchestrator.py)

Логика на стороне клиента:
- Управление историей сообщений
- AC1 — автоматическое сжатие
- AC3 — инъекция временного контекста
- AC4 — управление чекпоинтами

### PII Guard (pii_guard.py) 🛡️

Модуль маскирования чувствительных данных:
- Обнаружение PII с помощью Microsoft Presidio
- Поддержка Email, телефонов, имен, адресов
- Специфика РФ: паспорта, ИНН, российские телефоны
- Плейсхолдеры: `[MASKED_EMAIL]`, `[MASKED_PHONE]`, и т.д.

### Secure Middleware (secure_middleware.py) 🛡️

Безопасный прокси для LLM:
- Автоматическое PII маскирование перед отправкой
- Поддержка Anthropic Claude и OpenAI
- Логирование безопасности для аудита
- Интеграция с MCP сервером

### Утилиты (utils.py)

- `count_tokens()` — подсчет токенов с tiktoken
- Вспомогательные функции

## Безопасность

- ✅ **PII-маскирование** перед отправкой в LLM (Security Phase 3)
- ✅ **Microsoft Presidio** — индустриальный стандарт
- ✅ **Поддержка РФ** — паспорта, ИНН, телефоны
- ✅ **Secure Middleware** — прокси с автоматическим маскированием
- ✅ **TTL для данных** — 24h для памяти, 7 дней для чекпоинтов
- ✅ **Логирование** — аудит безопасности

### Поддерживаемые типы PII

| Тип | Плейсхолдер | Пример |
|-----|-------------|--------|
| Email | `[MASKED_EMAIL]` | ivan@example.com |
| Телефон | `[MASKED_PHONE]` | +7 (999) 123-45-67, 89991234567 |
| Имя | `[MASKED_NAME]` | Иван Иванов, Иванов-Смирнов Иван Петрович |
| Адрес | `[MASKED_ADDRESS]` | г. Москва, ул. Ленина |
| Паспорт РФ | `[MASKED_PASSPORT]` | 45 11 123456 |
| ИНН | `[MASKED_INN]` | 772816897563 |
| СНИЛС | `[MASKED_SNILS]` | 112-233-445 95 |
| Кредитная карта | `[MASKED_CARD]` | 4532 1234 5678 9010 |
| Банковский счет | `[MASKED_ACCOUNT]` | 40817810099910004321 |
| БИК | `[MASKED_BIC]` | 044525225 |
| Водительское удостоверение | `[MASKED_LICENSE]` | 77 11 123456 |
| Автомобильный номер | `[MASKED_PLATE]` | А123ВС 77 |
| Telegram | `[MASKED_TELEGRAM]` | @username |
| VK профиль | `[MASKED_VK]` | https://vk.com/id1234567 |
| Полис ОМС | `[MASKED_POLICY]` | 7755 1234567890 |

## Мониторинг и отладка

### Логи

Все основные операции логируются:
- `[INFO]` — информационные сообщения
- `[WARN]` — предупреждения
- `[ERROR]` — ошибки
- `[DEBUG]` — отладочная информация

### Статистика

Просмотр текущей статистики:

```python
# В интерактивном режиме:
stats

# Программно:
from src.host_orchestrator import ContextOrchestrator
orchestrator = ContextOrchestrator()
await orchestrator.connect()
print(orchestrator.get_stats())
```

## Остановка

```bash
# Остановка сервисов Docker
docker-compose down

# Полная очистка (с удалением volumes)
docker-compose down -v
```

## Troubleshooting

### Проблема: Redis недоступен

```bash
# Проверьте статус Redis
docker-compose ps

# Перезапустите Redis
docker-compose restart redis
```

### Проблема: OpenAI API ошибка

Убедитесь, что ключ указан в `.env` файле:
```bash
cat .env | grep OPENAI_API_KEY
```

### Проблема: Модуль не найден

Убедитесь, что вы установили зависимости:
```bash
pip install -r requirements.txt
```

### Проблема: spaCy модель не загружена

```bash
python -m spacy download en_core_web_lg
```

### Проблема: 403 Forbidden при запросах к LLM API

Ошибка `403 Forbidden` обычно означает региональное ограничение API. Решение - настройка прокси:

**Вариант 1: VLESS/Hiddify (рекомендуется)**

1. Установите зависимости:
```bash
pip install pyyaml requests
```

2. Настройте VLESS в `.env`:
```env
# Используя подписку Hiddify
VLESS_SUBSCRIPTION=https://hiddify.com/s/your_code

# Или прямую VLESS ссылку
VLESS_URL=vless://uuid@host:port?...
```

3. Запустите Xray клиент:
```bash
chmod +x run_vless.sh
./run_vless.sh start
```

4. Настройте прокси:
```env
ALL_PROXY=socks5://127.0.0.1:10809
```

5. Проверьте работу:
```bash
python3 test_vless.py
```

**Вариант 2: Прямой прокси**

1. Убедитесь, что `httpx` установлен:
```bash
pip install httpx>=0.24.0
```

2. Настройте прокси в `.env`:
```env
HTTP_PROXY=http://localhost:7890
# или
HTTP_PROXY=socks5://127.0.0.1:1080
```

3. Проверьте работу прокси:
```bash
python3 test_proxy.py
```

Подробнее:
- [docs/VLESS_HIDDIFY_SETUP.md](docs/VLESS_HIDDIFY_SETUP.md) - VLESS настройка
- [docs/PROXY_CONFIGURATION.md](docs/PROXY_CONFIGURATION.md) - Прямой прокси

## Лицензия

MIT License

## Контакты

Для вопросов и предложений создайте issue в репозитории.

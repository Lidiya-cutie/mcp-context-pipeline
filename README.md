# MCP Context Pipeline

ML-пайплайн для управления контекстом в MCP (Model Context Protocol) приложениях: PII-маскирование, сжатие контекста, набор MCP-серверов и навыков, eval-гейты и итеративная коррекция.

## Описание

Кроссплатформенное решение:
- **Windows** — локальная разработка
- **Ubuntu/Linux** — серверное окружение

Оркестрация инфраструктуры через **Docker Compose** (Redis, PostgreSQL, опционально Xray). Python-компоненты работают локально (stdio) или в контейнерах (SSE/HTTP). Управляющая консоль — **NiceGUI** (`mcp_ui.py`).

## Ключевые возможности

### Безопасность
- **PII Guard** (Microsoft Presidio): маскирование перед отправкой в LLM
- Специфика РФ: паспорта, ИНН, СНИЛС, телефоны и др.
- **Secure Middleware**: прокси к LLM с автоматическим маскированием
- MCP `pii_scanner` в наборе серверов

### Управление контекстом
- **AC1**: автосжатие при превышении порога
- **AC2**: инициативная суммаризация
- **AC3**: инъекция временного контекста
- **AC4**: чекпоинты сессии
- **AC5**: стресс-тесты на 100k+ токенов

### MCP-платформа и навыки
- **31 MCP-сервер** в `src/mcp_servers/` (stdio JSON-RPC): context_manager, agent_bus, pii_scanner, mlflow, redis, storage и др.
- **~61 навык** в `Навыки/`
- `skill_dispatcher.py` — диспетчер навыков
- `agent_executor.py` — запуск субагентов / вызовов MCP

### Knowledge Bridge и Context7
- Поиск внутренних стандартов (`search_standard`, `list_domains`, `get_best_practices`)
- Актуальная документация библиотек через Context7 MCP

### Итеративная коррекция (`pipeline/`)
- Цикл: генерация → F1 / semantic drift → hint → перегенерация
- Стоп: пороги или `PIPELINE_MAX_ITERATIONS`
- Пилот: `python -m pipeline.run_pilot`

### Оценка качества и эксперименты
- External knowledge / REST API / unified eval + GitHub Actions gates
- API compatibility (`src/api_compatibility.py`, см. `README_COMPAT.md`)
- Харнесс экспериментов: кросс-валидация LLM, бенчмарк инструкций, system prompts, code execution — `experiments/`, скрипты в `src/`

### Мультипровайдерность
- Anthropic API и Anthropic-compatible endpoint (например GLM через `ANTHROPIC_BASE_URL`)
- OpenAI (`OPENAI_API_KEY`)
- OpenRouter (`OPENROUTER_API_KEY`) для multi-model eval
- Переключение через `.env`

## Структура проекта

```
mcp_context_pipeline/
|-- docker-compose.yml
|-- docker-compose-xray.yml
|-- docker-compose-singbox.yml
|-- .env.example
|-- requirements.txt
|-- pytest.ini                 # testpaths = tests
|-- mcp_ui.py                  # NiceGUI-консоль (порт 7860)
|-- run_nicegui.sh
|-- run_host.sh / run_host.bat
|-- run_vless.sh
|-- run_unified_eval.py
|-- run_rest_api_eval.py
|-- run_external_knowledge_eval.py
|-- eval_queries_v*.jsonl
|-- src/
|   |-- server.py              # MCP: compress/checkpoint/memory + PII
|   |-- host_orchestrator.py
|   |-- knowledge_server.py
|   |-- context7_mcp_server.py
|   |-- pii_guard.py
|   |-- secure_middleware.py
|   |-- skill_dispatcher.py
|   |-- agent_executor.py
|   |-- api_compatibility.py / compat_cli.py
|   |-- mcp_servers/           # 31 сервер (manifest.json + server.py)
|   |-- external_knowledge/    # роутер внешних знаний
|   |-- cross_validation.py
|   |-- instruction_benchmark.py
|   |-- full_benchmark.py
|   |-- system_prompt_benchmark.py
|   |-- code_performance_benchmark.py
|   |-- run_experiments.py
|   |-- test_pipeline.py       # операционные AC1–AC5
|-- pipeline/                  # итеративная коррекция
|   |-- orchestrator.py
|   |-- run_pilot.py
|   |-- test_cases.py
|   |-- logger.py
|   |-- results/
|-- experiments/               # отчёты и JSON артефакты eval
|-- tests/                     # основной pytest-набор
|   |-- test_mcp_manifests.py  # structural smoke MCP-пакетов
|   |-- test_*.py              # epics, PII, external knowledge, REST…
|-- archive/
|   |-- gradio/                # прежняя UI
|   |-- smoke/                 # отладочные test_*.py (не CI)
|-- Навыки/                    # определения навыков
|-- xray-config/
|   |-- config.example.json    # шаблон без секретов
|   |-- config-singbox.example.json
|   |-- config.json            # локальный runtime (gitignore)
|-- docs/
|-- artifacts/
|-- data/
```

## Установка и запуск

### Требования

- Python 3.10+
- Docker и Docker Compose
- API-ключ LLM (Anthropic / compatible / OpenAI; для multi-model eval — OpenRouter)

### Шаг 1: Инфраструктура

```bash
docker compose up -d
docker compose ps
```

### Шаг 2: Зависимости

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Для NiceGUI при необходимости: `pip install nicegui` (если не подтянут транзитивно).

### Шаг 3: Переменные окружения

```bash
cp .env.example .env
```

Минимальный набор:

```env
LLM_PROVIDER=anthropic

# Official Anthropic или compatible (GLM/z.ai и т.п.)
ANTHROPIC_API_KEY=
ANTHROPIC_BASE_URL=
ANTHROPIC_MODEL=claude-sonnet-4-20250514

OPENAI_API_KEY=
OPENROUTER_API_KEY=

MAX_TOKENS=128000
SUMMARY_THRESHOLD=100000
ENABLE_PII_MASKING=true

# Пороги итеративной коррекции (см. pipeline/README.md)
PIPELINE_F1_THRESHOLD=0.95
PIPELINE_DRIFT_THRESHOLD=0.18
PIPELINE_MAX_ITERATIONS=5

HTTP_PROXY=
HTTPS_PROXY=
ALL_PROXY=
VLESS_URL=
VLESS_SUBSCRIPTION=
```

При региональных 403 к LLM API — прокси или VLESS (`docs/VLESS_HIDDIFY_SETUP.md`, `docs/PROXY_CONFIGURATION.md`).

**Xray:** runtime-конфиг не хранится в git. Скопируйте шаблон и заполните:

```bash
cp xray-config/config.example.json xray-config/config.json
# затем ./run_vless.sh start  — или сгенерируйте конфиг скриптом из VLESS_URL / подписки
```

### Шаг 4: Проверка

```bash
python verify_setup.py
```

### Шаг 5: Запуск хоста / тестов

```bash
chmod +x run_host.sh && ./run_host.sh
# или
python src/test_pipeline.py 4
```

### Веб-консоль (NiceGUI)

Порт **7860**, dark mode. Вкладки: Поиск знаний, Документация, PII & Безопасность, Эксперты, MCP Серверы, Система.

```bash
bash run_nicegui.sh
# или
.venv/bin/python mcp_ui.py
```

Открыть: http://localhost:7860

Gradio перенесён в `archive/gradio/` (Gradio 6 / Svelte 5 ломал multi-tab консоль при кастомном CSS).

## Итеративная коррекция

```bash
python -m pipeline.run_pilot
```

Пороги через env (default drift **0.18** — калибровка пилота; строгий research baseline — `0.15`):

```bash
PIPELINE_DRIFT_THRESHOLD=0.15 PIPELINE_MAX_ITERATIONS=3 python -m pipeline.run_pilot
```

Детали: `pipeline/README.md`. Артефакты: `pipeline/results/`, `pipeline/logs/*.jsonl`.

## Эксперименты и бенчмарки

| Скрипт | Назначение |
|--------|------------|
| `src/run_experiments.py` | кросс-валидация + instruction bench + поиск сжимающих инструкций |
| `src/cross_validation.py` | multi-LLM consensus / hallucination risk |
| `src/instruction_benchmark.py` | RU/EN формулировки инструкций |
| `src/full_benchmark.py` | полный прогон по `eval_queries_v3.jsonl` (RU/EN/PL) |
| `src/system_prompt_benchmark.py` | стабильность system prompts |
| `src/code_performance_benchmark.py` | исполнение сгенерированного кода в sandbox |

Отчёты и JSON: `experiments/`. Ключи только из env (без hardcoded secrets).

## API compatibility

```bash
python -m src.compat_cli --help
python -m pytest tests/test_api_compatibility.py -q
```

См. `README_COMPAT.md`, датасеты в `data/compat_example_*`, `data/openapi_v*.json`.

## Тестирование

### Операционные проверки хоста

```bash
python src/test_pipeline.py 1   # базовый
python src/test_pipeline.py 2   # стресс 100k+
python src/test_pipeline.py 3   # чекпоинты
python src/test_pipeline.py 4   # все
python src/test_pipeline.py 5   # интерактив
```

### Pytest (основной набор)

```bash
.venv/bin/pytest -q
# или по эпикам:
python tests/test_context_management.py
python tests/test_security_pii.py
python tests/test_performance_infra.py
python tests/test_model_evaluation.py
python tests/test_knowledge_bridge.py
python tests/test_context7_integration.py
.venv/bin/pytest tests/test_mcp_manifests.py -q
```

`test_mcp_manifests.py` — structural smoke: у каждого пакета в `src/mcp_servers/` есть `manifest.json` + компилируемый `server.py` (без live backend).

Полный прогон эпиков: `python tests/run_all_tests.py`.

Важно:
- `tests/` — поддерживаемый CI/регрессионный набор (`pytest.ini`: `testpaths = tests`)
- `archive/smoke/test_*.py` и `src/test_*.py` — отладка/smoke, не основной CI

### Epic-покрытие (кратко)

- **Epic 1** — сжатие, timestamps, чекпоинты, race в Redis
- **Epic 2** — PII (email/phone/passport/NER/leakage)
- **Epic 3** — нагрузка, memory leak, token accuracy
- **Epic 4** — shadow mode, semantic similarity, cost/latency, tool calling
- **Epic 5–6** — Knowledge Bridge, Context7
- **REST API eval** — `python run_rest_api_eval.py` (resource orientation, pagination, versioning, errors)

### Unified Evaluation

```bash
EVAL_DATASET_PATH=eval_queries_v3.jsonl REST_API_EVAL_DATASET=data/rest_api_eval_good.jsonl python run_unified_eval.py
```

Артефакты: `artifacts/unified_eval/`, `artifacts/rest_api_eval/`, `artifacts/external_knowledge_eval/`.

### CI/CD

Workflows: `external_knowledge_eval`, `rest_api_eval`, `unified_eval` (см. `.github/workflows/`, `docs/CI_CD_INTEGRATION.md`).

Gate (ориентиры):
- External Knowledge: Recall@K ≥ 0.60, MRR ≥ 0.45, Latency P95 ≤ 8000 ms
- REST API: overall ≥ 0.7, pagination ≥ 0.7, resource orientation ≥ 0.8

### PII Guard

```bash
python tests/test_pii_completeness.py --count 100
python tests/test_pii_integration.py
```

```python
from src.pii_guard import get_pii_guard

guard = get_pii_guard()
masked = guard.mask(
    "Меня зовут Иван Иванов, телефон +7 (999) 123-45-67, email ivan@example.com",
    language="en",
)
# [MASKED_NAME], [MASKED_PHONE], [MASKED_EMAIL]
```

### Knowledge Bridge / Context7 (программно)

```python
from src.host_orchestrator import ContextOrchestrator

orchestrator = ContextOrchestrator(enable_knowledge_bridge=True, enable_context7=True)
await orchestrator.connect()
print(await orchestrator.search_standard("api", "pagination"))
print(await orchestrator.query_library_docs("torch", "tensor operations"))
await orchestrator.disconnect()
```

Ресурсы KB: `kb://architecture/principles`, `kb://tech_stack`, `kb://coding_standards/python`, `kb://security/guidelines`.

Библиотеки Context7 (часть списка): torch, transformers, diffusers, fastapi, anthropic, openai, redis, postgresql, pillow, requests, pytest, celery, numpy, pandas, scipy.

### Результаты Russian PII (референс)

```
Total Tests: 84
Successful: 84 (100.0%)
Leakage Detected: 0
```

## Архитектура

### Инфраструктура
- **Redis** — сессии, кэш, саммари
- **PostgreSQL** — долгосрочная память
- **Xray/sing-box** (опционально) — прокси к LLM API

### Слой MCP
- `src/server.py` — compress_context, checkpoint, search_memory + PII
- `src/mcp_servers/*` — доменные инструменты (infra, MLOps, security, docs)
- `src/knowledge_server.py`, `src/context7_mcp_server.py` — знания и документация

### Хост и UI
- `host_orchestrator.py` — AC1/AC3/AC4, bridges
- `skill_dispatcher.py` / `agent_executor.py` — навыки и субагенты
- `mcp_ui.py` — NiceGUI-консоль

### Коррекция и eval
- `pipeline/` — замкнутый feedback-loop сжатия
- `experiments/` + `src/*benchmark*.py` — воспроизводимые прогоны
- `run_*_eval.py` + Actions — quality gates

### PII / Secure Middleware
- Presidio + RU-сущности; плейсхолдеры `[MASKED_*]`
- Прокси Anthropic/OpenAI с маскированием и audit-логом

## Безопасность

- PII-маскирование перед LLM
- Runtime Xray/VLESS-конфиги и `.env` не коммитятся
- TTL памяти/чекпоинтов; security logging

| Тип | Плейсхолдер | Пример |
|-----|-------------|--------|
| Email | `[MASKED_EMAIL]` | ivan@example.com |
| Телефон | `[MASKED_PHONE]` | +7 (999) 123-45-67 |
| Имя | `[MASKED_NAME]` | Иван Иванов |
| Адрес | `[MASKED_ADDRESS]` | г. Москва, ул. Ленина |
| Паспорт РФ | `[MASKED_PASSPORT]` | 45 11 123456 |
| ИНН | `[MASKED_INN]` | 772816897563 |
| СНИЛС | `[MASKED_SNILS]` | 112-233-445 95 |
| Карта | `[MASKED_CARD]` | 4532 1234 5678 9010 |
| Счёт | `[MASKED_ACCOUNT]` | 40817810099910004321 |
| БИК | `[MASKED_BIC]` | 044525225 |
| ВУ | `[MASKED_LICENSE]` | 77 11 123456 |
| Номер авто | `[MASKED_PLATE]` | А123ВС 77 |
| Telegram | `[MASKED_TELEGRAM]` | @username |
| VK | `[MASKED_VK]` | https://vk.com/id1234567 |
| ОМС | `[MASKED_POLICY]` | 7755 1234567890 |

Подробнее: `docs/PII_GUARD.md`, `docs/RUSSIAN_PII_SUPPORT.md`.

## Мониторинг

```python
from src.host_orchestrator import ContextOrchestrator
orchestrator = ContextOrchestrator()
await orchestrator.connect()
print(orchestrator.get_stats())
```

В интерактивном режиме: команда `stats`.

## Остановка

```bash
docker compose down
docker compose down -v   # с volumes
```

## Troubleshooting

**Redis:** `docker compose ps` / `docker compose restart redis`

**Модуль не найден:** `pip install -r requirements.txt` в активированном `.venv`

**spaCy:** `python -m spacy download en_core_web_lg`

**403 к LLM API:** настроить VLESS/прокси. Проверки:

```bash
./run_vless.sh start
python3 archive/smoke/test_vless.py
python3 archive/smoke/test_proxy.py
```

Compose монтирует `./xray-config/config.json` (локальный файл из example или `run_vless.sh`).  
При `invalid "privateKey"`: `./run_vless.sh stop && ./run_vless.sh start`, затем `docker logs --tail 30 mcp-xray-vless`.

## Чеклист перед push

```bash
git status
git check-ignore -v .env
git check-ignore -v xray-config/config.json
git ls-files .env xray-config/config.json
git diff --cached --name-only
```

- `.env` и `xray-config/config.json` (и прочие runtime Xray-конфиги) — не в индексе
- нет hardcoded API keys в staged diff
- author коммита — владелец репозитория (не agent identity)

```bash
git add .
git restore --staged .env xray-config/config.json 2>/dev/null || true
git commit -m "your message"
git push origin master
```

## Документация

- `docs/BEST_PRACTICES.md`
- `docs/CI_CD_INTEGRATION.md`
- `docs/CONTEXT7_INTEGRATION.md`
- `docs/PII_GUARD.md` / `docs/RUSSIAN_PII_SUPPORT.md`
- `docs/PROXY_CONFIGURATION.md` / `docs/VLESS_HIDDIFY_SETUP.md`
- `docs/REST_API_METRICS.md` / `docs/REST_API_IMPROVEMENTS.md`
- `pipeline/README.md`
- `README_COMPAT.md`
- `experiments/REPORT.md`

## Лицензия

MIT License

## Контакты

Issues в репозитории GitHub.

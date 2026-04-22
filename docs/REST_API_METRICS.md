# REST API Quality Metrics

## Обзор

Модуль для оценки качества REST API с объективными численными метриками.

## Метрики

### 1. Ресурсный подход (Resource Orientation)

**Цель:** >= 0.8

Проверяет соответствие URL путей и HTTP методов принципам REST.

**Формула:**
```
score = (noun_paths / total_endpoints) * 0.6 + (http_method_compliance / total_endpoints) * 0.4
```

**Критерии:**
- Путь должен быть ресурсно-ориентированным (noun-oriented)
  - Хорошо: `/api/v1/users`, `/api/v1/users/1`
  - Плохо: `/getUserList`, `/createUser`
- HTTP методы должны соответствовать операциям
  - GET для получения
  - POST для создания
  - PUT/PATCH для обновления
  - DELETE для удаления

### 2. Пагинация (Pagination)

**Цель:** >= 0.7

Проверяет наличие и согласованность пагинации для list-эндпоинтов.

**Формула:**
```
score = (endpoints_with_pagination / list_endpoints) * 0.3 +
        (has_total_count / list_endpoints) * 0.2 +
        (has_next_link / list_endpoints) * 0.2 +
        consistent_strategy * 0.3
```

**Критерии:**
- Наличие параметров пагинации (limit, offset, page, size)
- Наличие total/count в ответе
- Наличие next/next_link в ответе
- Согласованность стратегии (offset_limit, page_size, cursor)

### 3. Версионность (Versioning)

**Цель:** >= 0.6

Проверяет наличие и согласованность версионирования API.

**Формула:**
```
score = (version_in_path / total_endpoints) * 0.5 +
        (version_in_header / total_endpoints) * 0.3 +
        (version_in_query / total_endpoints) * 0.1 +
        consistent_versioning * 0.1
```

**Критерии:**
- Версия указана в пути (`/api/v1/users`)
- Версия указана в заголовке (`Accept-Version: v1`)
- Версия указана в query параметре (`?version=v1`)
- Используется один способ версионирования
- Все эндпоинты используют одну версию

### 4. Коды ошибок (Error Codes)

**Цель:** >= 0.7

Проверяет правильное использование HTTP кодов статуса.

**Формула:**
```
score = (appropriate_2xx / total_endpoints) * 0.4 +
        (meaningful_4xx / total_endpoints) * 0.3 +
        (1 if has_500 == 0 else 0) * 0.3
```

**Критерии:**
- Использование 2xx кодов (200, 201, 204)
- Использование осмысленных 4xx кодов (400, 401, 403, 404, 409, 422)
- Отсутствие 500 кодов (или минимальное количество)

### 5. Структурная избыточность (Structural Redundancy)

**Цель:** >= 0.6

Проверяет согласованность структуры ответов.

**Формула:**
```
score = (has_data_wrapper / total_endpoints) * 0.3 +
        (has_meta_section / total_endpoints) * 0.2 +
        (has_errors_section / total_endpoints) * 0.2 +
        consistent_structure * 0.3
```

**Критерии:**
- Наличие обертки данных (data, result, items)
- Наличие секции meta
- Наличие секции errors
- Согласованность структуры между эндпоинтами

## Общая оценка

**Цель:** >= 0.7

**Формула:**
```
overall_score = resource_score * 0.2 +
                pagination_score * 0.2 +
                versioning_score * 0.15 +
                error_codes_score * 0.25 +
                structural_score * 0.2
```

## Использование

### Базовое использование

```python
from src.rest_api_evaluator import RESTAPIEvaluator

evaluator = RESTAPIEvaluator(
    dataset_path="data/rest_api_eval_good.jsonl"
)
report = await evaluator.run()

print(f"Overall Score: {report['quality']['overall_score']:.2f}")
print(f"Status: {report['status']}")
```

### Экспорт артефактов

```python
report = await evaluator.run_and_export("artifacts/rest_api_eval")

# Создаются файлы:
# - rest_api_eval_report.json
# - rest_api_eval.prom (Prometheus формат)
# - rest_api_eval_summary.txt
```

### Запуск из CLI

```bash
# Оценка хорошего API
REST_API_EVAL_DATASET=data/rest_api_eval_good.jsonl python run_rest_api_eval.py

# Оценка плохого API
REST_API_EVAL_DATASET=data/rest_api_eval_poor.jsonl python run_rest_api_eval.py
```

## Формат данных

Каждая запись в файле данных (JSONL) должна содержать:

```json
{
  "id": "GET-001",
  "method": "GET",
  "path": "/api/v1/users",
  "version": "v1",
  "params": {"limit": 10, "offset": 0},
  "response": {
    "data": [{"id": 1, "name": "User 1"}],
    "meta": {"total": 100, "page": 1, "limit": 10},
    "errors": []
  },
  "status_code": 200,
  "headers": {"Accept-Version": "v1"}
}
```

## Конфигурация

Переменные окружения (`.env`):

```env
REST_API_EVAL_DATASET=data/rest_api_eval_good.jsonl
REST_API_EVAL_OUTPUT=artifacts/rest_api_eval
REST_API_EVAL_RECORD_LIMIT=
REST_API_MIN_RESOURCE_ORIENTATION=0.8
REST_API_MIN_PAGINATION=0.7
REST_API_MIN_VERSIONING=0.6
REST_API_MIN_ERROR_CODES=0.7
REST_API_MIN_STRUCTURAL_REDUNDANCY=0.6
REST_API_MIN_OVERALL_SCORE=0.7
```

## Unified Evaluation

Для запуска объединенной оценки внешних знаний и REST API:

```bash
EVAL_DATASET_PATH=eval_queries_v3.jsonl \
REST_API_EVAL_DATASET=data/rest_api_eval_good.jsonl \
python run_unified_eval.py
```

## Тестовые данные

- `data/rest_api_eval_good.jsonl` — пример хорошего REST API
- `data/rest_api_eval_poor.jsonl` — пример плохого REST API

## Тесты

```bash
# Тест evaluator'а
python tests/test_rest_api_evaluator.py

# Тест формул
python tests/test_rest_api_metrics_formulas.py

# Тест метрик
python tests/test_rest_api_metrics.py
```

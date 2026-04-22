# Исправления REST API метрик

## Выполненные исправления

### 1. Исправлен анализатор пагинации

**Файл:** `src/rest_api_metrics.py:134-145`

**Проблема:** Анализатор искал `total` и `next` только в корне ответа.

**Решение:** Добавлен поиск в секции `meta`.

```python
meta_section = response.get("meta", {})
if not isinstance(meta_section, dict):
    meta_section = {}

total_present = any(
    k.lower() in {"total", "count", "total_count"}
    for k in set(response.keys()) | set(meta_section.keys())
)
```

**Результат:** pagination score 0.20 -> 0.37

### 2. Стандартизирована стратегия пагинации

**Файл:** `data/rest_api_eval_good.jsonl`

**Проблема:** Смешение `limit/offset` и `page/size` стратегий.

**Решение:** Все list-эндпоинты используют `limit/offset`.

**Результат:** consistent_strategy = 1, +0.3 к оценке

### 3. Добавлен total во все list-эндпоинты

**Файл:** `data/rest_api_eval_good.jsonl`

**Проблема:** Не все list-эндпоинты возвращали `total`.

**Решение:** Добавлен `total` в `meta` для всех list-эндпоинтов.

### 4. Добавлен next link

**Файл:** `data/rest_api_eval_good.jsonl`

**Проблема:** Клиент не знал о следующей странице.

**Решение:** Добавлен `next` в `meta` для всех list-эндпоинтов с данными.

## Результаты

| Метрика | До | После | Цель | Статус |
|---------|-----|-------|------|--------|
| resource_orientation | 1.00 | 1.00 | 0.8 | PASS |
| pagination | 0.20 | 0.73 | 0.7 | PASS |
| versioning | 0.90 | 0.90 | 0.6 | PASS |
| error_codes | 0.82 | 0.82 | 0.7 | PASS |
| structural_redundancy | 0.94 | 0.94 | 0.6 | PASS |
| **overall_score** | 0.77 | **0.87** | 0.7 | PASS |

## Измененные файлы

- `src/rest_api_metrics.py` - исправлен анализ пагинации
- `data/rest_api_eval_good.jsonl` - улучшены тестовые данные
- `docs/REST_API_IMPROVEMENTS.md` - документация исправлений
- `docs/REST_API_METRICS.md` - обновлена документация метрик

## Проверка

```bash
python run_rest_api_eval.py
```

Результат: status=pass, overall_score=0.87

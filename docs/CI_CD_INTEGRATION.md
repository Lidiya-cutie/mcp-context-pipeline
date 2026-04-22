# CI/CD Integration

## Обзор

Проект использует GitHub Actions для CI/CD. Интегрированы три workflow для оценки качества:

1. **external_knowledge_eval** - оценка внешних знаний
2. **rest_api_eval** - оценка REST API качества
3. **unified_eval** - объединенная оценка

## Workflows

### 1. External Knowledge Eval

**Файл:** `.github/workflows/external_knowledge_eval.yml`

**Триггеры:**
- Manual (`workflow_dispatch`)
- Push в `src/external_knowledge/**`, `run_external_knowledge_eval.py`, `eval_queries_v*.jsonl`
- Pull request с теми же путями

**Проверяемые метрики:**
- Recall@K >= 0.60
- MRR >= 0.45
- Source Coverage >= 0.95
- Provenance Coverage >= 0.95
- Not Found Rate <= 0.20
- Latency P95 <= 8000ms
- Cache Hit Rate >= 0.20
- Fallback Success Rate >= 0.95

**Артефакты:**
- `external-knowledge-eval-artifacts`

### 2. REST API Eval

**Файл:** `.github/workflows/rest_api_eval.yml`

**Триггеры:**
- Manual (`workflow_dispatch`)
- Push в `src/rest_api_*.py`, `run_rest_api_eval.py`, `data/rest_api_eval_*.jsonl`
- Pull request с теми же путями

**Проверяемые метрики:**
- Resource Orientation >= 0.8
- Pagination >= 0.7
- Versioning >= 0.6
- Error Codes >= 0.7
- Structural Redundancy >= 0.6
- Overall Score >= 0.7

**Артефакты:**
- `rest-api-eval-artifacts`

### 3. Unified Eval

**Файл:** `.github/workflows/unified_eval.yml`

**Триггеры:**
- Manual (`workflow_dispatch`)
- Push в любые файлы оценки
- Pull request с теми же путями

**Проверяемые метрики:**
- Все метрики external_knowledge_eval
- Все метрики rest_api_eval

**Дополнительно:**
- Автоматический комментарий в PR с результатами
- Проверка общего статуса (pass/fail)

**Артефакты:**
- `unified-eval-artifacts`

## Локальный запуск перед коммитом

### External Knowledge Eval

```bash
python run_external_knowledge_eval.py
```

### REST API Eval

```bash
python run_rest_api_eval.py
```

### Unified Eval

```bash
EVAL_DATASET_PATH=eval_queries_v3.jsonl \
REST_API_EVAL_DATASET=data/rest_api_eval_good.jsonl \
python run_unified_eval.py
```

## Gate Checks

Все workflow выполняют gate checks:

```bash
# Проверка статуса
status=$(python -c "import json; print(json.load(open('artifacts/.../report.json'))['status'])")

# Если status != pass, workflow падает с ошибкой
if [ "$status" != "pass" ]; then
  echo "Eval failed"
  exit 1
fi
```

## Конфигурация порогов

### External Knowledge

Переменные окружения (`.env`):
```env
EVAL_MIN_RECALL_AT_K=0.60
EVAL_MIN_MRR=0.45
EVAL_MIN_SOURCE_COVERAGE=0.95
EVAL_MIN_PROVENANCE_COVERAGE=0.95
EVAL_MAX_NOT_FOUND_RATE=0.20
EVAL_MAX_P95_MS=8000
EVAL_MIN_CACHE_HIT_RATE=0.20
EVAL_MIN_FALLBACK_SUCCESS_RATE=0.95
```

### REST API

Переменные окружения (`.env`):
```env
REST_API_MIN_RESOURCE_ORIENTATION=0.8
REST_API_MIN_PAGINATION=0.7
REST_API_MIN_VERSIONING=0.6
REST_API_MIN_ERROR_CODES=0.7
REST_API_MIN_STRUCTURAL_REDUNDANCY=0.6
REST_API_MIN_OVERALL_SCORE=0.7
```

## Запуск workflows

### Manual trigger

1. Перейдите в GitHub Actions
2. Выберите workflow
3. Нажмите "Run workflow"

### Push trigger

```bash
git add .
git commit -m "Update external knowledge evaluation"
git push
```

Workflow запустится автоматически.

### Pull request trigger

При создании или обновлении PR workflow запустится автоматически и добавит комментарий с результатами.

## Результаты в PR

Unified eval добавляет комментарий:

```
## Unified Evaluation Results

Overall Status: PASS

### External Knowledge
- Status: pass
- Recall@K: 1.0000
- MRR: 0.5000
- Latency P95: 1.10ms
- Cache Hit Rate: 0.5000

### REST API
- Status: pass
- Overall Score: 0.8742
- Resource Orientation: 1.0000
- Pagination: 0.7333
- Versioning: 0.9000
- Error Codes: 0.8167
- Structural Redundancy: 0.9417

---
Generated at: 2026-04-22T10:16:25.386470+00:00
```

## Устранение неполадок

### Workflow не запускается

Проверьте пути в `on:` секции workflow.

### Eval не проходит

1. Запустите локально: `python run_..._eval.py`
2. Проверьте `artifacts/.../..._report.json`
3. Найдите failed gate checks
4. Исправьте код или данные
5. Проверьте снова локально

### Артефакты не загружаются

Проверьте права доступа к директории `artifacts/`.

## Оптимизация

### Кэширование зависимостей

```yaml
- name: Cache pip dependencies
  uses: actions/cache@v4
  with:
    path: ~/.cache/pip
    key: ${{ runner.os }}-pip-${{ hashFiles('**/requirements.txt') }}
    restore-keys: |
      ${{ runner.os }}-pip-
```

### Параллельный запуск

Jobs запускаются параллельно по умолчанию.

### Условный запуск

```yaml
on:
  push:
    branches:
      - main
      - develop
```

## Мониторинг

Результаты всех запусков доступны в GitHub Actions:

1. Перейдите в репозиторий
2. Нажмите "Actions"
3. Выберите workflow
4. Просмотрите историю запусков

## Дополнительные ресурсы

- [GitHub Actions Documentation](https://docs.github.com/en/actions)
- [Workflow Syntax](https://docs.github.com/en/actions/reference/workflow-syntax-for-github-actions)
- [Artifacts](https://docs.github.com/en/actions/using-workflows/storing-workflow-data-as-artifacts)

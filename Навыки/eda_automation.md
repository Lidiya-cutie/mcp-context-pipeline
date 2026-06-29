---
name: "Exploratory Data Analysis Automation"
role: "Data Scientist"
trigger: "Первичный анализ нового датасета, поиск аномалий, визуализация распределений"
priority: medium
allowed_tools: ["python", "bash", "mcp:clickhouse_read"]
context_rules:
 include: ["src/eda/", "config/eda_profiles.yaml"]
 exclude: ["*.png", "cache/"]
memory_integration: true
worktree_isolation: false
---
## Цель
Автоматическая генерация EDA-отчёта: missing values, outliers, correlations, target distribution.

## Алгоритм
1. Загрузить профиль EDA.
2. Запустить `python scripts/eda_run.py --dataset $DS --profile $PRF`.
3. Сгенерировать `eda_report.html` + `summary.json`.
4. Сохранить выводы в память.

## Интеграции
- MCP: `clickhouse_read`.
- `.claudeignore`: игнорировать `*.png`, оставлять `summary.json`.

## Ограничения
- Лимит строк: 500k (sample если >).
- Запрет на отправку сырых данных в LLM.

## Вывод
HTML-отчёт + JSON-саммари с `anomalies`, `correlations`, `data_quality_score`.

## Фоллбэк
При memory error → переключиться на Dask и уменьшить batch.

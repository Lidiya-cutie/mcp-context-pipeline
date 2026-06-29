---
name: "Metric-Driven Hypothesis Testing"
role: "Data Scientist"
trigger: "Запуск AB-теста, проверка статгипотез, валидация метрик модерации"
priority: high
allowed_tools: ["python", "mcp:clickhouse_read", "mcp:jira_read"]
context_rules:
 include: ["src/stats/", "notebooks/hypothesis/"]
 exclude: ["*.ipynb_checkpoints", "tmp/"]
memory_integration: true
worktree_isolation: false
---
## Цель
Автоматизация проверки гипотез с расчётом p-value, мощности теста и доверительных интервалов.

## Алгоритм
1. Считать когорты из ClickHouse через MCP.
2. Выбрать тест (t-test, Mann-Whitney, bootstrap) на основе нормальности и размера выборок.
3. Рассчитать метрики, сформировать отчёт.
4. Сохранить в `агент-память/hypotheses/`.

## Интеграции
- MCP: `jira_read` для линковки с тикетом.
- `.claudeignore`: игнорировать промежуточные CSV.

## Ограничения
- При n < 30 → принудительный bootstrap.
- Запрет на p-hacking: фиксация альфа до запуска.

## Вывод
`markdown`-отчёт с таблицей метрик, графиком распределения, статусом `REJECT/FAIL_TO_REJECT`.

## Фоллбэк
Если данные не сходятся по схемам → запросить `mcp:clickhouse_schema` и скорректировать JOIN.

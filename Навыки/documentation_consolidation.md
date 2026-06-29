---
name: "Cross-Session Knowledge Consolidation"
role: "Data Scientist"
trigger: "Сбор выводов из нескольких сессий, квартальный отчёт, фиксация архитектурных решений"
priority: medium
allowed_tools: ["python", "bash", "mcp:jira_read"]
context_rules:
 include: ["агент-память/", "reports/"]
 exclude: ["tmp/", "*.log"]
memory_integration: true
worktree_isolation: false
---
## Цель
Агрегация разрозненных инсайтов, метрик и решений в единый структурированный отчёт.

## Алгоритм
1. Считать все `.md` и `.json` из `агент-память/`.
2. Кластеризовать по темам (модели, данные, метрики).
3. Сгенерировать `consolidated_report.md`.
4. Зафиксировать версию в памяти.

## Интеграции
- MCP: `jira_read` для линковки с задачами.
- Память: `reports/consolidated/v{date}.md`.

## Ограничения
- Только проверенные данные (status: validated).
- Запрет на speculation без пометки `[HYPOTHESIS]`.

## Вывод
Markdown-отчёт с `executive_summary`, `technical_decisions`, `next_steps`.

## Фоллбэк
При конфликтах данных → пометить `CONFLICT` и запросить верификацию.

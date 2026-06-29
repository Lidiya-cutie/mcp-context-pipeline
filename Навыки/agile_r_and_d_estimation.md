---
name: "Agile R&D Estimation"
role: "Data Scientist"
trigger: "Оценка сложности исследовательских задач, планирование спринта, T-shirt/Fibonacci"
priority: medium
allowed_tools: ["bash", "python", "mcp:jira_read"]
context_rules:
 include: ["src/estimation/", "history/sprint_metrics.yaml"]
 exclude: ["*.log"]
memory_integration: true
worktree_isolation: false
---
## Цель
Оценка задач на основе исторических данных спринтов и сложности R&D-контекста.

## Алгоритм
1. Загрузить историю из `агент-память/sprints/`.
2. Применить эвристику: `complexity = (data_uncertainty + model_novelty + infra_dependency)`.
3. Сопоставить с Fibonacci/T-shirt шкалой.
4. Вернуть оценку + риски.

## Интеграции
- MCP: `jira_read` для описания задач.
- Память: обновить `estimation_log`.

## Ограничения
- Запрет на оценку без исторического контекста (fallback → S).
- Учёт block-факторов.

## Вывод
`task_id: S/M/L/XL | fib: 3/5/8/13 | risks: [] | confidence: 0.8`.

## Фоллбэк
При отсутствии аналогов → запросить уточняющие вопросы у лида.

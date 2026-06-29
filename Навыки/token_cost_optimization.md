---
name: "Cost & Token Usage Optimization"
role: "MLOps"
trigger: "Анализ эффективности Claude Code, авто-тюнинг .claudeignore, бюджет-контроль"
priority: medium
allowed_tools: ["bash", "python", "mcp:usage_api"]
context_rules:
 include: ["cost/", "config/token_budget.yaml"]
 exclude: ["*.log", "tmp/"]
memory_integration: true
worktree_isolation: false
---
## Цель
Минимизация токенов без потери качества: динамический `.claudeignore`, контекст-фильтрация.

## Алгоритм
1. Считать `usage_metrics` из `mcp:usage_api`.
2. Проанализировать `token_per_task`.
3. Оптимизировать `.claudeignore`, зафиксировать `savings`.
4. Уведомить при breach бюджета.

## Интеграции
- MCP: `usage_api` (Anthropic console).
- `.claudeignore`: авто-обновление.

## Ограничения
- Запрет на исключение `Навыки/`, `src/`.
- Фиксация `optimization_hash`.

## Вывод
`cost_report.json` с `tokens_used`, `savings`, `budget_status`, `recommendations`.

## Фоллбэк
При breach → throttle non-critical agents, notify lead.

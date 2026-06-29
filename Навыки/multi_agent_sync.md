---
name: "Multi-Agent Workflow Design"
role: "ML Engineer"
trigger: "Параллельная работа кодера и тестировщика, синхронизация контекстов"
priority: high
allowed_tools: ["bash", "git", "mcp:agent_bus"]
context_rules:
 include: ["agents/", "config/agent_roles.yaml"]
 exclude: ["tmp/", "*.log"]
memory_integration: true
worktree_isolation: true
---
## Цель
Координация субагентов: изолированные контексты, общий state, конфликтоустойчивость.

## Алгоритм
1. Инициализировать агентов через `mcp:agent_bus`.
2. Назначить роли: `coder`, `tester`, `reviewer`.
3. Синхронизировать через `shared_state.json` в `агент-память/`.
4. Мерджить результаты после валидации.

## Интеграции
- MCP: `agent_bus` (pub/sub для state).
- Worktrees: 1 агент = 1 worktree.

## Ограничения
- Запрет на прямой доступ к файлам других агентов.
- Lock при записи в `shared_state`.

## Вывод
`sync_log.json` с `agent_statuses`, `merge_result`, `conflicts`.

## Фоллбэк
При deadlock → таймаут 5 мин, принудительный kill и рестарт.

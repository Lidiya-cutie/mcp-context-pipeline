---
name: "E2E Workflow Orchestration"
role: "QA"
trigger: "Кросс-сервисные сценарии: загрузка → ML-обработка → UI-отображение → нотификация"
priority: high
allowed_tools: ["bash", "playwright", "mcp:api_gateway", "mcp:db_read"]
context_rules:
 include: ["tests/e2e/", "flows/"]
 exclude: ["screenshots/", "videos/"]
memory_integration: true
worktree_isolation: true
---
## Цель
Валидация сквозных бизнес-процессов с учётом асинхронности ML-очередей и состояния UI.

## Алгоритм
1. Инициализировать clean state через API.
2. Запустить Playwright-сценарий с polling ML-status.
3. Валидировать финальный UI + DB state.
4. Записать `flow_status` в память.

## Интеграции
- MCP: `api_gateway`, `db_read`, `playwright`.
- `.claudeignore`: скрыть `videos/`, оставить `e2e_report.json`.

## Ограничения
- Таймаут на async-операции: 30s.
- Запрет на shared state между runs.

## Формат вывода
`{"flow_id": "...", "steps_passed": "4/4", "latency_ms": 1200, "status": "PASS"}`

## Фоллбэк
При async timeout → retry 2x, затем escalate к ML/Backend team.

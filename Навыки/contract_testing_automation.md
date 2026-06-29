---
name: "Contract Testing Automation"
role: "QA"
trigger: "Проверка совместимости API между frontend, backend и ML-сервисами, OpenAPI валидация"
priority: high
allowed_tools: ["bash", "python", "mcp:openapi_spec"]
context_rules:
 include: ["specs/", "tests/contract/"]
 exclude: ["node_modules/", "dist/"]
memory_integration: true
worktree_isolation: false
---
## Цель
Предотвращение breaking changes через автоматическое сравнение текущей реализации с утверждённым контрактом.

## Алгоритм
1. Сгенерировать спецификацию из кода (`fastapi openapi`, `swagger`).
2. Сравнить с `specs/contract_v{N}.yaml` через `mcp:openapi_spec`.
3. Запустить `pact`/`specmatic` тесты.
4. Записать `contract_status` в память.

## Интеграции
- MCP: `openapi_spec` для diff-анализа.
- `.claudeignore`: скрыть генерируемые `.json` файлы.

## Ограничения
- Blocking CI при `breaking_changes > 0`.
- Только approved spec updates.

## Формат вывода
`contract_diff.md` + `compatibility_score: 0-100%`.

## Фоллбэк
При breaking change → авто-генерация миграционного гайда, блокировка мержа до согласования.

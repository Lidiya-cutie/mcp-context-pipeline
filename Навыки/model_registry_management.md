---
name: "Automated Model Registry Management"
role: "MLOps"
trigger: "Регистрация модели, присвоение тегов, promotion Staging → Production"
priority: high
allowed_tools: ["bash", "python", "mcp:mlflow"]
context_rules:
 include: ["registry/", "config/promotion_rules.yaml"]
 exclude: ["*.mlruns", "tmp/"]
memory_integration: true
worktree_isolation: true
---
## Цель
Централизованное управление версиями, автоматическая promotion при passing checks.

## Алгоритм
1. Валидировать `evaluation_card.md`.
2. Запустить `mlflow register --name $MODEL --stage staging`.
3. При `metrics.delta > baseline` → `promotion_rules.yaml` → `production`.
4. Записать `registry_state` в память.

## Интеграции
- MCP: `mlflow` для registry API.
- Память: `registry/history.json`.

## Ограничения
- Запрет на promotion без тестов.
- Фиксация `model_uri`.

## Вывод
`registry_update.json` с `model_id`, `stage`, `promoted_by`, `checks_passed`.

## Фоллбэк
При fail promotion → откат к `previous_stable`, алерт.

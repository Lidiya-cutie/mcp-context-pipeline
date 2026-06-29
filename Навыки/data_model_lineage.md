---
name: "Data & Model Lineage Orchestration"
role: "MLOps"
trigger: "Фиксация связей: датасет → фичи → модель → метрики → деплой"
priority: high
allowed_tools: ["python", "bash", "mcp:lineage_db"]
context_rules:
 include: ["lineage/", "config/graph_schema.yaml"]
 exclude: ["tmp/", "*.log"]
memory_integration: true
worktree_isolation: false
---
## Цель
Сквозная трассировка: какая версия данных породила какую модель, с какими метриками.

## Алгоритм
1. Парсить артефакты из `агент-память/`.
2. Строить граф через `graph_schema.yaml`.
3. Сохранять в `mcp:lineage_db`.
4. Генерировать `lineage_report.json`.

## Интеграции
- MCP: `lineage_db` (Neo4j/MLMD).
- Память: `lineage/graph_v{date}.json`.

## Ограничения
- Только проверенные артефакты.
- Запрет на перезапись графа.

## Вывод
`lineage_report.json` с `dataset_hash`, `model_uri`, `metrics`, `deploy_id`.

## Фоллбэк
При разрыве цепи → пометить `BROKEN`, запросить ручной фикс.

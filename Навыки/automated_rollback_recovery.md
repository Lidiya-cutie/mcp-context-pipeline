---
name: "Automated Recovery & Rollback Skills"
role: "MLOps"
trigger: "Сбой деплоя, падение метрик, критические ошибки инференса"
priority: critical
allowed_tools: ["bash", "docker", "mcp:registry"]
context_rules:
 include: ["recovery/", "config/rollback_rules.yaml"]
 exclude: ["*.log", "tmp/"]
memory_integration: true
worktree_isolation: true
---
## Цель
Автоматический откат к стабильной версии при fail: анализ логов, переключение routing, валидация.

## Алгоритм
1. Парсить `error_logs` через `rollback_rules.yaml`.
2. Найти `last_stable` в registry.
3. Применить `traffic_shift.sh`, запустить `health_check`.
4. Записать `rollback_event` в память.

## Интеграции
- MCP: `registry` для версий.
- Память: `recovery/history.json`.

## Ограничения
- Только авто-rollback при severity: critical.
- Фиксация `rollback_hash`.

## Вывод
`rollback_report.json` с `from_version`, `to_version`, `status`, `post_check`.

## Фоллбэк
При fail rollback → manual override, escalate to on-call.

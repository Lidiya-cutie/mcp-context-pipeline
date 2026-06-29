---
name: "Incident Response & Runbook Automation"
role: "DevOps"
trigger: "Аварийное реагирование, авто-выполнение runbook, postmortem генерация, escalation"
priority: critical
allowed_tools: ["bash", "python", "mcp:pagerduty", "mcp:k8s", "mcp:monitoring"]
context_rules:
 include: ["runbooks/", "config/incident_rules.yaml"]
 exclude: ["*.log", "tmp/"]
memory_integration: true
worktree_isolation: false
---
## Цель
Сокращение MTTR: автоматический запуск сценариев восстановления, сбор контекста, генерация отчёта.

## Алгоритм
1. Получить alert из `mcp:pagerduty`.
2. Выбрать runbook по `incident_rules.yaml`.
3. Выполнить шаги: restart, rollback, scale, notify.
4. Сгенерировать `postmortem_draft.md`, сохранить в память.

## Интеграции
- MCP: `pagerduty`, `k8s`, `monitoring`.
- Память: `incidents/history.json`.

## Ограничения
- Только confirmed incidents.
- Фиксация `incident_id`, все действия логируются.

## Формат вывода
`{"incident_id": "...", "mttr_min": 12, "runbook_status": "COMPLETED", "postmortem_link": "..."}`

## Фоллбэк
При fail → manual takeover, escalate to SRE lead, preserve logs.

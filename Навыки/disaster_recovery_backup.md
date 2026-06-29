---
name: "Disaster Recovery & Backup Orchestration"
role: "DevOps"
trigger: "Создание backup БД/состояний, валидация RPO/RTO, автоматический failover drill"
priority: critical
allowed_tools: ["bash", "velero", "pg_dump", "mcp:storage"]
context_rules:
 include: ["backups/", "config/dr_plans.yaml"]
 exclude: ["*.sql", "tmp/"]
memory_integration: true
worktree_isolation: false
---
## Цель
Гарантия восстановления: регулярные снапшоты, cross-region replication, автоматические тесты restore.

## Алгоритм
1. Запустить `velero backup create` + `pg_dump`.
2. Реплицировать в secondary region.
3. Запустить dry-run restore в sandbox.
4. Валидировать RPO/RTO, сохранить отчёт.

## Интеграции
- MCP: `storage`, `k8s`.
- `.claudeignore`: скрыть raw dumps, оставить `dr_report.json`.

## Ограничения
- Only encrypted backups.
- Запрет на тесты в prod.

## Формат вывода
`{"backup_status": "SUCCESS", "rpo_min": 5, "rto_min": 15, "restore_test": "PASS"}`

## Фоллбэк
При restore fail → escalate, increase frequency, manual audit.

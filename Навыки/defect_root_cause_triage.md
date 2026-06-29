---
name: "Defect Root Cause Triage"
role: "QA"
trigger: "Анализ баг-репортов, парсинг логов, авто-классификация severity, линковка с кодом"
priority: high
allowed_tools: ["python", "bash", "mcp:logs", "mcp:git_blame"]
context_rules:
 include: ["logs/", "triage/", "config/severity_rules.yaml"]
 exclude: ["*.zip", "tmp/"]
memory_integration: true
worktree_isolation: false
---
## Цель
Автоматический разбор инцидентов: стек-трейс, корреляция с коммитами, приоритизация, черновик JIRA.

## Алгоритм
1. Парсить логи через `mcp:logs`, извлечь stack trace.
2. Запустить `git blame` на ключевые строки.
3. Классифицировать severity по `severity_rules.yaml`.
4. Сгенерировать `triage_report.md` + draft JIRA.

## Интеграции
- MCP: `logs`, `git_blame`, `jira_read`.
- Память: `triage/history.json`.

## Ограничения
- Только staging/prod-логи.
- Фиксация `incident_id`.

## Формат вывода
`{"severity": "HIGH", "suspect_commit": "...", "root_cause_prob": 0.85, "draft_jira": {...}}`

## Фоллбэк
При неоднозначности → запросить additional logs, пометить `[NEEDS_REVIEW]`.

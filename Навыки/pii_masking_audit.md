---
name: "PII Masking Audit"
role: "MLOps"
trigger: "Регулярный аудит конфигов, логов и MCP-потоков на утечку PII"
priority: critical
allowed_tools: ["bash", "python", "mcp:pii_scanner"]
context_rules:
 include: ["audit/", "config/compliance_rules.yaml"]
 exclude: ["*.log", "tmp/"]
memory_integration: true
worktree_isolation: false
---
## Цель
Проверка соответствия GDPR/152-ФЗ: сканирование `.mcp.json`, логов, контекста.

## Алгоритм
1. Запустить `mcp:pii_scanner` на целевых файлах.
2. Сравнить с `compliance_rules.yaml`.
3. Сформировать `audit_report.json`.
4. При breach → block pipeline, notify security.

## Интеграции
- MCP: `pii_scanner`.
- `.claudeignore`: скрыть сырые логи, оставить `audit/`.

## Ограничения
- Zero-trust: любой raw PII → fail.
- Фиксация `audit_hash`.

## Вывод
`audit_report.json` с `scanned_files`, `pii_found`, `compliance_status`.

## Фоллбэк
При обнаружении → авто-маскировка, принудительный re-scan.

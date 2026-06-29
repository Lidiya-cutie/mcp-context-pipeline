---
name: "PII & Context Masking Protocol"
role: "Data Scientist"
trigger: "Подготовка данных для отправки в LLM, экспорт в облако, публикация отчётов"
priority: critical
allowed_tools: ["python", "bash", "mcp:pii_scanner"]
context_rules:
 include: ["src/masking/", "rules/pii_patterns.yaml"]
 exclude: ["*.log", "tmp/"]
memory_integration: false
worktree_isolation: false
---
## Цель
Автоматическое обнаружение и маскирование PII перед передачей контекста в Claude или внешние MCP.

## Алгоритм
1. Запустить `mcp:pii_scanner` на целевых файлах.
2. Применить хеширование/замену по `rules/pii_patterns.yaml`.
3. Проверить `diff` до/после.
4. Заблокировать отправку при обнаружении unmasked PII.

## Интеграции
- MCP: `pii_scanner`, `.mcp.json` должен иметь `"masking": true`.
- `.claudeignore`: исключить исходные файлы с PII.

## Ограничения
- Строгий запрет на raw PII в контексте.
- Логирование всех маскировок в `audit/pii_log.json`.

## Вывод
`masked_data/` + `audit_report.json` с `blocked_count`, `replaced_fields`.

## Фоллбэк
При false-positive > 5% → обновить regex-правила и перезапустить.

---
name: "AI-Assisted Code Refactoring & Modernization"
role: "Fullstack"
trigger: "Модернизация legacy, удаление dead code, type safety, dependency updates"
priority: high
allowed_tools: ["bash", "typescript", "mcp:static_analysis"]
context_rules:
 include: ["src/", "config/refactor_rules.yaml"]
 exclude: ["node_modules/", "dist/"]
memory_integration: true
worktree_isolation: true
---
## Цель
Безопасный рефакторинг: AI-анализ зависимостей, авто-типизация, удаление неиспользуемого кода.

## Алгоритм
1. Запустить AST-анализ через `mcp:static_analysis`.
2. Выявить `dead_code`, `any` types, outdated deps.
3. Применить авто-рефакторинг с `--dry-run` валидацией.
4. Создать PR, сохранить отчёт.

## Интеграции
- MCP: `static_analysis`, `git`.
- `.claudeignore`: скрыть `temp_repos/`, оставить `refactor_report.json`.

## Ограничения
- Только approved deps.
- Mandatory tests pass before merge.

## Формат вывода
`{"files_refactored": 15, "any_removed": 8, "dead_code_kb": 42, "test_status": "PASS"}`

## Фоллбэк
При break → revert PR, log error, manual review.

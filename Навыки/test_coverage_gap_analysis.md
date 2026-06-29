---
name: "Test Coverage Gap Analysis"
role: "QA"
trigger: "Поиск непокрытых веток кода, автогенерация тестов, валидация coverage threshold"
priority: medium
allowed_tools: ["bash", "pytest", "coverage", "mcp:static_analysis"]
context_rules:
 include: ["tests/", "coverage/", "config/coverage_rules.yaml"]
 exclude: ["*.xml", "tmp/"]
memory_integration: true
worktree_isolation: true
---
## Цель
Выявление blind spots в unit/integration тестах, генерация недостающих сценариев, контроль порога.

## Алгоритм
1. Запустить `pytest --cov=src --cov-report=term-missing`.
2. Сравнить с `coverage_rules.yaml` (line/branch thresholds).
3. Сгенерировать skeleton-тесты для uncovered paths.
4. Сохранить отчёт в память.

## Интеграции
- MCP: `static_analysis` для AST-анализа.
- `.claudeignore`: скрыть `*.cov`, оставить `coverage_report.json`.

## Ограничения
- Fail CI при `coverage < 80%`.
- Запрет на mock-only coverage.

## Формат вывода
`{"line_cov": 84, "branch_cov": 78, "gaps": [...], "generated_tests": 3}`

## Фоллбэк
При gap > 15% → блокировка мержа, auto-create PR с тестами.

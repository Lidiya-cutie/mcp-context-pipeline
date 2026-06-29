---
name: "Accessibility Compliance Audit"
role: "QA"
trigger: "Проверка WCAG 2.2 AA, screen reader compatibility, contrast validation, keyboard navigation"
priority: medium
allowed_tools: ["bash", "axe-core", "mcp:lighthouse"]
context_rules:
 include: ["tests/a11y/", "config/a11y_rules.yaml"]
 exclude: ["*.log", "tmp/"]
memory_integration: true
worktree_isolation: false
---
## Цель
Автоматизированный аудит доступности интерфейсов с формированием actionable-рекомендаций.

## Алгоритм
1. Запустить `axe-core` + `lighthouse` через MCP.
2. Сравнить с `a11y_rules.yaml`.
3. Сгенерировать отчёт с приоритизацией fixes.
4. Сохранить в память, линковать с PR.

## Интеграции
- MCP: `lighthouse`, `axe-core`.
- `.claudeignore`: исключить `*.jsonl`, оставить `a11y_summary.md`.

## Ограничения
- Только validated routes.
- Запрет на игнорирование `critical` issues.

## Формат вывода
`{"score": 92, "violations": [], "critical_fixes": [], "compliance": "WCAG_2.2_AA"}`

## Фоллбэк
При score < 85 → блокировка мержа, авто-генерация исправлений CSS/ARIA.

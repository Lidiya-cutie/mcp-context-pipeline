---
name: "Cross-Platform Responsive Validation"
role: "Fullstack"
trigger: "Валидация адаптивности, device matrix testing, offline fallbacks, touch optimization"
priority: medium
allowed_tools: ["bash", "playwright", "mcp:lighthouse"]
context_rules:
 include: ["styles/", "tests/responsive/"]
 exclude: ["screenshots/", "tmp/"]
memory_integration: true
worktree_isolation: false
---
## Цель
Гарантия UX на всех устройствах: mobile-first, touch targets, offline resilience.

## Алгоритм
1. Запустить `playwright` на device matrix (iOS/Android/Desktop).
2. Валидировать breakpoints, touch targets >= 44px.
3. Проверить `offline` режим через Service Worker.
4. Сохранить отчёт в память.

## Интеграции
- MCP: `playwright`, `lighthouse`.
- `.claudeignore`: скрыть `videos/`, оставить `responsive_report.json`.

## Ограничения
- Fail if touch target < 44px.
- Mandatory offline fallback.

## Формат вывода
`{"devices_tested": 6, "breakpoint_failures": 0, "offline_status": "OK", "status": "PASS"}`

## Фоллбэк
При fail → auto-generate CSS fixes, retest.

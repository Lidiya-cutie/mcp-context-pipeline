---
name: "Component Design System Synchronization"
role: "Fullstack"
trigger: "Синхронизация UI-компонентов с дизайн-токенами, Storybook валидация, cross-platform consistency"
priority: high
allowed_tools: ["bash", "storybook", "mcp:figma_api"]
context_rules:
 include: ["ui/", "tokens/", "stories/"]
 exclude: ["node_modules/", "dist/"]
memory_integration: true
worktree_isolation: false
---
## Цель
Единый источник правды для UI: авто-генерация компонентов из токенов, валидация в Storybook.

## Алгоритм
1. Считать дизайн-токены из `mcp:figma_api`.
2. Сгенерировать CSS/TS переменные.
3. Запустить `storybook test` + snapshot validation.
4. Сохранить `sync_status` в память.

## Интеграции
- MCP: `figma_api`, `storybook`.
- `.claudeignore`: скрыть `storybook_static/`, оставить `token_audit.json`.

## Ограничения
- Только approved tokens.
- Zero hard-coded values.

## Формат вывода
`{"components_synced": 12, "token_mismatches": 0, "snapshot_status": "PASS"}`

## Фоллбэк
При mismatch → auto-generate PR с обновлёнными стилями, notify designer.

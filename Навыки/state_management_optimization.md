---
name: "State Management Profiling & Optimization"
role: "Fullstack"
trigger: "Профилирование Redux/Zustand/RTK Query, memoization, cache invalidation, re-render analysis"
priority: high
allowed_tools: ["bash", "react-devtools", "mcp:lighthouse"]
context_rules:
 include: ["store/", "config/state_rules.yaml"]
 exclude: ["node_modules/", "tmp/"]
memory_integration: true
worktree_isolation: false
---
## Цель
Устранение лишних ререндеров, оптимизация селекторов, настройка TTL кэша данных.

## Алгоритм
1. Запустить React DevTools Profiler.
2. Выявить `render_count > 3` per interaction.
3. Применить `React.memo`, `useMemo`, оптимизировать selectors.
4. Валидировать через `mcp:lighthouse`, сохранить отчёт.

## Интеграции
- MCP: `lighthouse`, `react_devtools`.
- `.claudeignore`: скрыть `profiles/`, оставить `perf_report.json`.

## Ограничения
- Запрет на mutable state outside store.
- Фиксация `baseline_metrics`.

## Формат вывода
`{"rerenders_reduced": 45, "memory_peak_mb": 82, "lighthouse_perf": 92}`

## Фоллбэк
При regression → revert selector changes, manual audit.

---
name: "Frontend Performance & Core Web Vitals Audit"
role: "Fullstack"
trigger: "Оптимизация bundle, lazy loading, image optimization, CWV compliance"
priority: high
allowed_tools: ["bash", "webpack", "mcp:lighthouse"]
context_rules:
 include: ["src/", "config/perf_rules.yaml"]
 exclude: ["node_modules/", "dist/"]
memory_integration: true
worktree_isolation: false
---
## Цель
Достижение CWV targets: LCP < 2.5s, CLS < 0.1, INP < 200ms.

## Алгоритм
1. Анализ bundle через `webpack-bundle-analyzer`.
2. Применить code splitting, preconnect, next-gen images.
3. Запустить `lighthouse` CI.
4. Сравнить с `perf_rules.yaml`, сохранить отчёт.

## Интеграции
- MCP: `lighthouse`, `cdn_api`.
- `.claudeignore`: скрыть `build_maps/`, оставить `cwv_report.json`.

## Ограничения
- Fail if `LCP > 2.5s`.
- Only optimized assets in prod.

## Формат вывода
`{"LCP": 1.8, "CLS": 0.05, "INP": 120, "bundle_size_kb": 145, "status": "PASS"}`

## Фоллбэк
При breach → auto-split chunk, defer non-critical JS, retest.

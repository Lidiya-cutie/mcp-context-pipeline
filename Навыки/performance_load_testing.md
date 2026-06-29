---
name: "Performance & Load Testing Orchestration"
role: "QA"
trigger: "Нагрузочное тестирование API, ML-инференс под нагрузкой, поиск bottlenecks"
priority: high
allowed_tools: ["bash", "k6", "locust", "mcp:monitoring"]
context_rules:
 include: ["tests/load/", "config/load_profiles.yaml"]
 exclude: ["*.log", "traces/"]
memory_integration: true
worktree_isolation: true
---
## Цель
Валидация SLA: p95 latency, error rate, throughput при масштабировании запросов.

## Алгоритм
1. Загрузить профиль из `load_profiles.yaml`.
2. Запустить `k6 run script.js --vus 500 --duration 5m`.
3. Агрегировать метрики через `mcp:monitoring`.
4. Сравнить с baseline, сохранить в память.

## Интеграции
- MCP: `monitoring` (Prometheus) для real-time метрик.
- `.claudeignore`: скрыть `k6_raw/`, оставить `sla_report.json`.

## Ограничения
- Запуск только в staging/isolated env.
- Auto-stop при `error_rate > 1%`.

## Формат вывода
`{"p50": 45, "p95": 180, "rps": 1200, "errors": "0.2%", "sla_status": "PASS"}`

## Фоллбэк
При SLA breach → сгенерировать flamegraph, создать инцидент, предложить оптимизацию.

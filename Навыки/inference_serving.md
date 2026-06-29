---
name: "Real-time Inference Serving & API Hardening"
role: "ML Engineer"
trigger: "Деплой инференс-сервера, настройка Triton/FastAPI, защита от abuse"
priority: high
allowed_tools: ["bash", "docker", "mcp:api_gateway"]
context_rules:
 include: ["server/", "config/api_ratelimit.yaml"]
 exclude: ["*.log", "tmp/"]
memory_integration: true
worktree_isolation: true
---
## Цель
Стабильный serving: latency < 200ms, rate limiting, circuit breaker, health checks.

## Алгоритм
1. Собрать Docker-образ с `tritonserver`.
2. Применить `api_ratelimit.yaml`.
3. Запустить `health_check.sh`, проверить `p99 latency`.
4. Записать `server_status` в память.

## Интеграции
- MCP: `api_gateway` для метрик.
- `.claudeignore`: скрыть `access.log`, оставить `metrics.json`.

## Ограничения
- Запрет на деплой без circuit breaker.
- Фиксация `max_concurrent_requests`.

## Вывод
`deploy_report.json` с `p50/p99_latency`, `error_rate`, `rate_limit_status`.

## Фоллбэк
При timeout > 1s → включить fallback-модель, алерт в Slack.

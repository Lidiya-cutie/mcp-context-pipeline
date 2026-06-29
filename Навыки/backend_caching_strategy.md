---
name: "Backend Caching & Cache Stampede Prevention"
role: "Fullstack"
trigger: "Настройка Redis/Memcached, TTL tuning, cache warming, stampede mitigation"
priority: high
allowed_tools: ["bash", "redis-cli", "mcp:redis"]
context_rules:
 include: ["cache/", "config/cache_policies.yaml"]
 exclude: ["*.log", "tmp/"]
memory_integration: true
worktree_isolation: false
---
## Цель
Снижение DB load: стратегический кэш, предотвращение thundering herd, graceful degradation.

## Алгоритм
1. Применить `cache_policies.yaml`.
2. Настроить `Redis Cluster`, включить pipelining.
3. Реализовать `cache warming` + `mutex lock` для stampede.
4. Валидировать hit rate, сохранить конфиг.

## Интеграции
- MCP: `redis`, `db_read`.
- `.claudeignore`: скрыть `redis_logs/`, оставить `cache_report.json`.

## Ограничения
- Max memory <= 80% limit.
- Only idempotent queries cached.

## Формат вывода
`{"hit_rate": "88%", "avg_latency_ms": 12, "stampede_blocked": 3, "status": "OPTIMAL"}`

## Фоллбэк
При miss > 30% → warm cache, increase TTL, notify backend.

---
name: "Real-Time Data Sync & Conflict Resolution"
role: "Fullstack"
trigger: "WebSockets/SSE, offline-first patterns, state reconciliation, CRDT integration"
priority: high
allowed_tools: ["bash", "socket.io", "mcp:db_read"]
context_rules:
 include: ["sync/", "config/sync_rules.yaml"]
 exclude: ["*.log", "tmp/"]
memory_integration: true
worktree_isolation: false
---
## Цель
Надёжная синхронизация данных в real-time: offline queue, conflict resolution, graceful reconnect.

## Алгоритм
1. Настроить WebSocket/SSE pipeline.
2. Реализовать offline queue + exponential backoff.
3. Применить CRDT/last-write-wins стратегию.
4. Валидировать consistency, сохранить конфиг.

## Интеграции
- MCP: `db_read`, `api_gateway`.
- `.claudeignore`: скрыть `socket_logs/`, оставить `sync_audit.json`.

## Ограничения
- Max reconnect attempts <= 5.
- Conflict log mandatory.

## Формат вывода
`{"sync_latency_ms": 80, "offline_queue_size": 0, "conflicts_resolved": 2, "status": "STABLE"}`

## Фоллбэк
При desync → force pull, notify user, log incident.

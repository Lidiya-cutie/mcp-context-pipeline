---
name: "API Gateway Rate Limiting & Auth Routing"
role: "Fullstack"
trigger: "Настройка Kong/Apigee, JWT валидация, abuse prevention, ML-endpoint routing"
priority: high
allowed_tools: ["bash", "kong", "mcp:api_gateway"]
context_rules:
 include: ["gateway/", "config/routing_rules.yaml"]
 exclude: ["*.log", "tmp/"]
memory_integration: true
worktree_isolation: false
---
## Цель
Защита API: rate limiting, JWT/OIDC валидация, роутинг на ML-сервисы, circuit breaking.

## Алгоритм
1. Применить `routing_rules.yaml` к gateway config.
2. Настроить rate limits per endpoint/IP.
3. Внедрить circuit breaker для ML-эндпоинтов.
4. Валидировать auth flow, сохранить конфиг.

## Интеграции
- MCP: `api_gateway`, `vault` (keys).
- `.claudeignore`: скрыть `gateway_logs/`, оставить `gateway_audit.json`.

## Ограничения
- Zero hard-coded secrets.
- Only allowlisted origins.

## Формат вывода
`{"routes_configured": 8, "rate_limit_applied": true, "auth_status": "VALID", "circuit_breaker": "ACTIVE"}`

## Фоллбэк
При auth fail → log & block IP, notify security.

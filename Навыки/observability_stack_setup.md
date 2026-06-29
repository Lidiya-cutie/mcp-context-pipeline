---
name: "Observability Stack Orchestration"
role: "DevOps"
trigger: "Настройка OpenTelemetry, Prometheus/Grafana, distributed tracing, ML-API метрики"
priority: high
allowed_tools: ["bash", "helm", "mcp:k8s", "mcp:monitoring"]
context_rules:
 include: ["monitoring/", "config/otel.yaml"]
 exclude: ["*.log", "tmp/"]
memory_integration: true
worktree_isolation: false
---
## Цель
Централизованный сбор логов, метрик, трейсов для backend, frontend и ML-сервисов.

## Алгоритм
1. Развернуть OTel collector через Helm.
2. Настроить exporters в Prometheus/Grafana.
3. Инструментировать API/ML-эндпоинты.
4. Валидировать pipeline, сохранить конфиг в память.

## Интеграции
- MCP: `k8s`, `monitoring`.
- `.claudeignore`: скрыть `otel_logs/`, оставить `dashboard_urls.json`.

## Ограничения
- Sampling rate <= 10% для prod.
- Запрет на хранение raw PII в логах.

## Формат вывода
`{"collector_status": "RUNNING", "dashboards_created": 3, "traces_enabled": true}`

## Фоллбэк
При exporter fail → fallback на local buffering, alert on-call.

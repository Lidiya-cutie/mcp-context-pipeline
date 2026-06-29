---
name: "Proactive Model Decay Monitoring"
role: "MLOps"
trigger: "Падение метрик в продакшене, концепт-дрейф, авто-триггер переобучения"
priority: critical
allowed_tools: ["bash", "python", "mcp:monitoring"]
context_rules:
 include: ["monitoring/", "config/decay_thresholds.yaml"]
 exclude: ["*.log", "tmp/"]
memory_integration: true
worktree_isolation: false
---
## Цель
Мониторинг decay: accuracy drop, data drift, latency spike → авто-переобучение.

## Алгоритм
1. Считать метрики из `mcp:monitoring`.
2. Сравнить с `decay_thresholds.yaml`.
3. При breach → создать JIRA, запустить `retrain_pipeline.sh`.
4. Записать `decay_event` в память.

## Интеграции
- MCP: `monitoring` (Prometheus/Grafana).
- Память: `decay/events.json`.

## Ограничения
- Подтверждение перед retrain.
- Фиксация `drift_score`.

## Вывод
`decay_alert.json` с `metric`, `threshold`, `action`, `retrain_status`.

## Фоллбэк
При false positive → recalibrate thresholds, alert MLOps.

---
name: "K8s Custom Metrics Autoscaling (HPA/VPA)"
role: "DevOps"
trigger: "Тюнинг HPA/VPA по GPU/очереди, предотвращение thrashing, cost-aware scaling"
priority: high
allowed_tools: ["bash", "kubectl", "mcp:k8s", "mcp:prometheus"]
context_rules:
 include: ["autoscaling/", "config/hpa_profiles.yaml"]
 exclude: ["*.log", "tmp/"]
memory_integration: true
worktree_isolation: false
---
## Цель
Динамическое масштабирование на основе бизнес-метрик (queue depth, GPU util, latency).

## Алгоритм
1. Загрузить `hpa_profiles.yaml`.
2. Применить `kubectl apply -f hpa.yaml` с custom metrics adapter.
3. Валидировать stability window, cooldown periods.
4. Сохранить `scaling_events` в память.

## Интеграции
- MCP: `k8s`, `prometheus`.
- `.claudeignore`: скрыть `k8s_logs/`, оставить `autoscale_report.json`.

## Ограничения
- Max replicas <= budget limit.
- Запрет на scale-to-zero для critical services.

## Формат вывода
`{"hpa_status": "ACTIVE", "current_replicas": 3, "target_metrics": {...}, "stability": "OK"}`

## Фоллбэк
При thrashing → increase stabilization window, alert DevOps.

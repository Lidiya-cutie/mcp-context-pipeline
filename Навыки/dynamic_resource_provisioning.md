---
name: "Dynamic Resource Provisioning"
role: "MLOps"
trigger: "Выделение GPU/CPU под задачу на основе T-shirt sizing и приоритета"
priority: high
allowed_tools: ["bash", "python", "mcp:k8s"]
context_rules:
 include: ["config/resource_map.yaml", "scripts/provision.py"]
 exclude: ["*.log", "cache/"]
memory_integration: true
worktree_isolation: true
---
## Цель
Автоматическое масштабирование под задачи: S → 1xA100, M → 2x, L → 4x + high RAM.

## Алгоритм
1. Считать `tshirt_size` из задачи.
2. Запросить доступные ноды через `mcp:k8s`.
3. Запустить `provision.py --size $SIZE --ttl 4h`.
4. Записать `allocation_id` в память.

## Интеграции
- MCP: `k8s` для node scheduling.
- `.claudeignore`: скрыть `pod_logs/`, оставить `allocation.json`.

## Ограничения
- Авто-скал down после TTL.
- Запрет на over-provisioning без approval.

## Вывод
`allocation_report.json` с `node`, `gpu_count`, `ttl`, `cost_estimate`.

## Фоллбэк
При недоступности → очередь, уведомление, эскалация.

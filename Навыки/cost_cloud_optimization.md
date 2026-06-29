---
name: "Cloud Cost Optimization & Rightsizing"
role: "DevOps"
trigger: "Анализ idle ресурсов, spot instance adoption, budget alerts, tagging compliance"
priority: medium
allowed_tools: ["bash", "python", "mcp:cloud_billing", "mcp:k8s"]
context_rules:
 include: ["cost/", "config/cost_rules.yaml"]
 exclude: ["*.csv", "tmp/"]
memory_integration: true
worktree_isolation: false
---
## Цель
Снижение cloud-spend: выявление неэффективных инстансов, авто-scale down, резервации.

## Алгоритм
1. Считать billing/metrics через MCP.
2. Выявить `cpu < 10%` или `memory < 20%` > 7 дней.
3. Предложить downsize/spot, применить через IaC.
4. Записать `savings_estimate` в память.

## Интеграции
- MCP: `cloud_billing`, `k8s`.
- `.claudeignore`: скрыть raw invoices, оставить `optimization_report.json`.

## Ограничения
- Только non-critical workloads.
- Approval для prod changes.

## Формат вывода
`{"savings_monthly": "$X", "resources_optimized": 3, "status": "APPLIED/PENDING"}`

## Фоллбэк
При perf degradation → revert, notify engineering.

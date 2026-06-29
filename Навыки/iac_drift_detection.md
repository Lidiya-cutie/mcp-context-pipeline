---
name: "IaC Drift Detection"
role: "MLOps"
trigger: "Проверка соответствия Terraform/Ansible конфигов и текущего состояния кластера"
priority: high
allowed_tools: ["bash", "terraform", "mcp:cloud_provider"]
context_rules:
 include: ["infra/", "config/cluster_baseline.yaml"]
 exclude: ["*.tfstate", "cache/"]
memory_integration: true
worktree_isolation: false
---
## Цель
Автоматическое обнаружение drift: версии CUDA, Python, GPU-драйверы, сетевые политики.

## Алгоритм
1. Запустить `terraform plan -detailed-exitcode`.
2. Сравнить с `cluster_baseline.yaml`.
3. Классифицировать drift: `safe`, `risky`, `critical`.
4. Записать отчёт в `агент-память/infra/`.

## Интеграции
- MCP: `cloud_provider` (AWS/GCP/YC).
- `.claudeignore`: скрыть `.tfstate`, оставить `drift_report.json`.

## Ограничения
- Запрет на auto-apply без approval.
- Фиксация `drift_hash`.

## Вывод
`drift_report.json` с `changes`, `severity`, `recommended_action`.

## Фоллбэк
При critical drift → остановить деплой, создать JIRA-инцидент.

---
name: "Infrastructure Drift Remediation"
role: "DevOps"
trigger: "Обнаружение drift Terraform/Ansible, авто-синхронизация состояния, валидация compliance"
priority: high
allowed_tools: ["bash", "terraform", "ansible", "mcp:cloud_provider"]
context_rules:
 include: ["infra/", "state/", "config/drift_rules.yaml"]
 exclude: ["*.tfstate", "cache/"]
memory_integration: true
worktree_isolation: false
---
## Цель
Автоматическое выявление и исправление расхождений между IaC и реальным облачным состоянием.

## Алгоритм
1. Запустить `terraform plan -detailed-exitcode`.
2. Сравнить с `drift_rules.yaml` (safe vs risky changes).
3. При safe → `terraform apply -auto-approve`, risky → create PR.
4. Записать `drift_event` в память.

## Интеграции
- MCP: `cloud_provider` (AWS/GCP/YC).
- `.claudeignore`: скрыть `.tfstate`, оставить `drift_report.json`.

## Ограничения
- Zero auto-apply для production infra.
- Фиксация `plan_hash`.

## Формат вывода
`{"drift_count": 2, "severity": "LOW", "action": "APPLY/PR", "status": "SUCCESS"}`

## Фоллбэк
При conflict → lock state, notify lead, manual review required.

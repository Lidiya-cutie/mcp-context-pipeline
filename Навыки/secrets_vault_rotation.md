---
name: "Secrets Vault & Rotation Automation"
role: "DevOps"
trigger: "Автоматическая ротация токенов, DB credentials, API keys, аудит доступа"
priority: critical
allowed_tools: ["bash", "vault", "mcp:secrets_manager"]
context_rules:
 include: ["secrets/", "config/rotation_policies.yaml"]
 exclude: ["*.env", "tmp/"]
memory_integration: false
worktree_isolation: false
---
## Цель
Zero-trust управление секретами: авто-ротация, audit trail, интеграция с k8s/CI.

## Алгоритм
1. Считать `rotation_policies.yaml`.
2. Вызвать `vault token rotate` / `aws secrets rotate`.
3. Обновить k8s secrets, рестарт pod'ов с graceful drain.
4. Записать `rotation_log` в audit-память.

## Интеграции
- MCP: `secrets_manager`.
- `.claudeignore`: исключить все файлы с `secret`, `key`, `token`.

## Ограничения
- Только через vault/manager API.
- Блокировка при `access_anomaly`.

## Формат вывода
`{"rotated_count": 4, "status": "SUCCESS", "audit_id": "sha256:...", "next_rotation": "..."}`

## Фоллбэк
При fail → keep old secret active, alert security, manual intervention.

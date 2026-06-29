---
name: "Network Policy & Zero-Trust Hardening"
role: "DevOps"
trigger: "Настройка ingress/egress, service mesh, изоляция микросервисов, контроль lateral movement"
priority: high
allowed_tools: ["bash", "istioctl", "kubectl", "mcp:k8s"]
context_rules:
 include: ["networking/", "config/istio_rules.yaml"]
 exclude: ["*.log", "tmp/"]
memory_integration: true
worktree_isolation: false
---
## Цель
Реализация zero-trust: mTLS, namespace isolation, egress control, DDoS mitigation.

## Алгоритм
1. Развернуть Istio sidecar injector.
2. Применить `NetworkPolicy` + `AuthorizationPolicy`.
3. Протестировать connectivity, заблокировать non-essential egress.
4. Записать `policy_status` в память.

## Интеграции
- MCP: `k8s`, `istio_api`.
- `.claudeignore`: скрыть `proxy_logs/`, оставить `network_audit.json`.

## Ограничения
- Только allow-list traffic.
- Фиксация `policy_version`.

## Формат вывода
`{"mTLS": "STRICT", "blocked_egress": 3, "policy_applied": true, "compliance": "ZERO_TRUST"}`

## Фоллбэк
При connectivity loss → revert to `v{N-1}`, notify SRE.

---
name: "Secure Auth & Session Management Integration"
role: "Fullstack"
trigger: "OAuth2/OIDC, MFA, secure cookies, session rotation, CSRF/XSS protection"
priority: critical
allowed_tools: ["bash", "oauth2-proxy", "mcp:vault"]
context_rules:
 include: ["auth/", "config/security_headers.yaml"]
 exclude: ["*.log", "tmp/"]
memory_integration: false
worktree_isolation: false
---
## Цель
Enterprise-grade auth: secure token flow, session hardening, compliance headers.

## Алгоритм
1. Настроить `oauth2-proxy` + OIDC provider.
2. Применить `SameSite=Strict`, `HttpOnly`, `Secure` cookies.
3. Внедрить CSRF tokens, CSP headers.
4. Протестировать flow, сохранить конфиг.

## Интеграции
- MCP: `vault`, `api_gateway`.
- `.claudeignore`: скрыть `auth_logs/`, оставить `security_audit.json`.

## Ограничения
- Zero session fixation vectors.
- Mandatory MFA for admin roles.

## Формат вывода
`{"auth_flow": "VALID", "headers_applied": true, "mfa_enforced": true, "status": "SECURE"}`

## Фоллбэк
При vuln → block route, rotate tokens, alert security.

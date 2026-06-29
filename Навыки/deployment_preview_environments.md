---
name: "Deployment Preview Environments Automation"
role: "Fullstack"
trigger: "PR-based ephemeral envs, auto-teardown, Vercel/Netlify/GitHub Pages, staging parity"
priority: medium
allowed_tools: ["bash", "vercel", "mcp:ci_platform"]
context_rules:
 include: ["deploy/", "config/preview_rules.yaml"]
 exclude: ["*.log", "tmp/"]
memory_integration: true
worktree_isolation: false
---
## Цель
Мгновенные preview-окружения для каждого PR: parity with staging, auto-teardown, QA access.

## Алгоритм
1. Триггер на PR open/update.
2. Развернуть через `vercel`/`netlify` с `env=preview`.
3. Инжект test data, сгенерировать shareable link.
4. Настроить TTL 7d, auto-teardown.

## Интеграции
- MCP: `ci_platform`, `storage`.
- `.claudeignore`: скрыть `deploy_logs/`, оставить `preview_report.json`.

## Ограничения
- No prod DB access.
- TTL enforcement mandatory.

## Формат вывода
`{"preview_url": "...", "env_hash": "...", "ttl_hours": 168, "status": "DEPLOYED"}`

## Фоллбэк
При deploy fail → notify author, fallback to local preview, retry.
